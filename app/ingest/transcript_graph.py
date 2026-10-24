"""Speaker-labeled transcript -> graph. OWNER: Person A.

Turns a "Speaker N: ..." transcript (or a solo debrief) into graph nodes and edges — who was met, what was
discussed, what each side promised — through Person B's `app.graph.writes` seam (via graph_bridge), and records a
LinkedIn handle if one was said. The route saves the raw transcript to cache/transcripts/ before calling this, so a
failed conversion never loses a recording.
"""
from app.agent import store
from app.contract import SessionExtract
from app.ingest import extract as extract_mod
from app.ingest import graph_bridge


def convert(session_id: str, transcript: str) -> tuple[str, SessionExtract | None]:
    """Return (graph_status, extract). Status: "built", "no_person" (nobody identifiable), or "failed: …"."""
    try:
        x = extract_mod.extract(session_id, transcript)
    except extract_mod.NoPersonFound:
        return "no_person", None
    except Exception as e:  # extraction is an LLM call; keep the transcript even if it fails
        return f"failed: {str(e)[:120]}", None
    graph_bridge.ingest_session(x)
    if linkedin := extract_mod.LINKEDIN.pop(session_id, None):
        store.set_linkedin(x.person.name, linkedin)
    if persona := extract_mod.PERSONA.pop(session_id, None):
        store.set_persona(x.person.name, persona)
    return "built", x


def build(session_id: str, transcript: str) -> str:
    """Graph status only (kept for callers that don't need the extract)."""
    return convert(session_id, transcript)[0]

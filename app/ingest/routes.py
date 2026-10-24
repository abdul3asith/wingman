"""POST /sessions, POST /sessions/{id}/process, POST /sessions/debrief-text — OWNER: Person A."""
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.contract import SessionExtract
from app.graph import queries
from app.ingest import extract as extract_mod
from app.ingest import graph_bridge, transcribe
from app.ingest.deepgram import TranscriptionError

router = APIRouter(prefix="/sessions", tags=["ingest"])

# Uploaded-but-unprocessed sessions. Process writes everything to the graph, so this can stay in memory.
_pending: dict[str, dict] = {}


class DebriefText(BaseModel):
    text: str


def _new_sid() -> str:
    return "s_" + uuid4().hex[:8]


def _run(sid: str, text: str, background: BackgroundTasks, sync_enrich: bool) -> SessionExtract:
    """extract -> write to graph -> enrich the company (background unless sync_enrich)."""
    try:
        x = extract_mod.extract(sid, text)
    except extract_mod.NoPersonFound as e:
        raise HTTPException(422, str(e))
    graph_bridge.ingest_session(x)
    if linkedin := extract_mod.LINKEDIN.pop(sid, None):
        from app.agent import store

        store.set_linkedin(x.person.name, linkedin)
    if x.company:
        if sync_enrich:
            graph_bridge.enrich_company(x.company.name, x.company.domain)
        else:
            background.add_task(graph_bridge.enrich_company, x.company.name, x.company.domain)
    background.add_task(_research_person, x.person.name)  # Bright Data people intel, never blocks the response
    return x


def _research_person(name: str) -> None:
    from app.agent import intel

    try:
        intel.research(name)
    except Exception as e:
        print(f"[ingest] background research for {name} failed: {e}")


@router.post("/debrief-text", response_model=SessionExtract)
def debrief_text(req: DebriefText, background: BackgroundTasks, sync_enrich: bool = False):
    """Demo insurance: typed debrief, no mic or transcription needed. Creates and processes in one call."""
    if not req.text.strip():
        raise HTTPException(400, "text is empty")
    return _run(_new_sid(), req.text.strip(), background, sync_enrich)


@router.post("")
async def create_session(audio: UploadFile | None = File(None), transcript: str | None = Form(None)):
    """Upload an audio blob (MediaRecorder webm) OR a raw transcript. Returns the session id."""
    if audio is None and not transcript:
        raise HTTPException(400, "send `audio` (multipart file) or `transcript` (form field)")
    sid = _new_sid()
    audio_path = None
    if audio is not None:
        ext = Path(audio.filename or "clip.webm").suffix or ".webm"
        audio_path = settings.CACHE_DIR / "audio" / f"{sid}{ext}"
        audio_path.write_bytes(await audio.read())
    _pending[sid] = {"audio_path": str(audio_path) if audio_path else None, "transcript": transcript}
    return {"session_id": sid, "status": "uploaded", "has_audio": audio_path is not None}


@router.post("/{sid}/process", response_model=SessionExtract)
def process_session(sid: str, background: BackgroundTasks, sync_enrich: bool = False):
    """Transcribe -> extract -> write to graph -> enrich the company (background unless sync_enrich=true)."""
    pending = _pending.get(sid)
    if pending is None:
        raise HTTPException(404, f"session {sid} not found or already processed")
    try:
        text = pending["transcript"] or transcribe.transcribe_file(pending["audio_path"])
    except TranscriptionError as e:
        # Keep the upload pending so the user can retry /process.
        raise HTTPException(502, str(e))
    if not text.strip():
        raise HTTPException(422, "transcription came back empty — try again or use the typed debrief")
    x = _run(sid, text, background, sync_enrich)
    _pending.pop(sid, None)  # only forget the upload once it is safely in the graph
    return x


@router.get("")
def list_sessions():
    return queries.sessions(settings.USER_ID)


@router.get("/{sid}")
def get_session(sid: str):
    out = queries.session_detail(settings.USER_ID, sid)
    if out is None:
        raise HTTPException(404, f"session {sid} not found")
    return out

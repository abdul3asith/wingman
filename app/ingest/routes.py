"""POST /sessions, POST /sessions/{id}/process, POST /sessions/debrief-text — OWNER: Person A."""
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.contract import SessionExtract
from app.graph import queries
from app.ingest import graph_bridge, transcribe, transcript_graph
from app.ingest.deepgram import TranscriptionError
from app.ingest.turns import parse_text, to_text

router = APIRouter(prefix="/sessions", tags=["ingest"])

# Uploaded-but-unprocessed sessions. Process saves the transcript to disk, so this can stay in memory.
_pending: dict[str, dict] = {}


class ProcessResult(BaseModel):
    """Response of /process. Ingest-local on purpose: contract.py is frozen and this never crosses the A/B seam."""

    session_id: str
    transcript: str
    graph_status: str  # built | no_person | failed: … (of the first conversation with a person)
    extract: SessionExtract | None = None  # first person met (kept for older callers)
    conversations: list[dict] = []  # one per conversation: session_id, start, end, extract, facts, category, …


class DebriefText(BaseModel):
    text: str


def _new_sid() -> str:
    return "s_" + uuid4().hex[:8]


def _save_transcript(sid: str, text: str) -> None:
    out = settings.CACHE_DIR / "transcripts" / f"{sid}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)


def _enrich(x: SessionExtract, background: BackgroundTasks, sync: bool) -> None:
    if not x.company:
        return
    if sync:
        graph_bridge.enrich_company(x.company.name, x.company.domain)
    else:
        background.add_task(graph_bridge.enrich_company, x.company.name, x.company.domain)
    # People intel (Bright Data LinkedIn/news) runs from the UI via POST /agent/research so the user sees it happen.


@router.post("/debrief-text", response_model=SessionExtract)
def debrief_text(req: DebriefText, background: BackgroundTasks, sync_enrich: bool = False):
    """Demo insurance: typed debrief, no mic or transcription needed. Creates and processes in one call."""
    if not req.text.strip():
        raise HTTPException(400, "text is empty")
    sid = _new_sid()
    _save_transcript(sid, req.text.strip())
    conv = transcript_graph.build_recording(sid, parse_text(req.text.strip()))[0]
    if conv["extract"] is None:
        status = conv["graph_status"]
        raise HTTPException(422, "couldn't tell who you met — say their name and try again" if status == "no_person" else status)
    x = SessionExtract(**conv["extract"])
    _enrich(x, background, sync_enrich)
    return x


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
        # Stream to disk in chunks: an hour of opus at 32 kbps is ~15 MB, no need to hold it in memory.
        with audio_path.open("wb") as f:
            while chunk := await audio.read(1 << 20):
                f.write(chunk)
    _pending[sid] = {"audio_path": str(audio_path) if audio_path else None, "transcript": transcript}
    return {"session_id": sid, "status": "uploaded", "has_audio": audio_path is not None}


@router.post("/{sid}/process", response_model=ProcessResult)
def process_session(sid: str, background: BackgroundTasks, sync_enrich: bool = False):
    """Transcribe (or take the pasted text) -> save to cache/transcripts -> extract who was met -> graph."""
    pending = _pending.get(sid)
    if pending is None:
        raise HTTPException(404, f"session {sid} not found or already processed")
    try:
        turns = parse_text(pending["transcript"]) if pending["transcript"] else transcribe.transcribe_turns(pending["audio_path"])
    except TranscriptionError as e:
        # Keep the upload pending so the user can retry /process.
        raise HTTPException(502, str(e))
    text = to_text(turns)
    if not text.strip():
        raise HTTPException(422, "transcription came back empty — try again or use the typed debrief")
    _save_transcript(sid, text)
    _pending.pop(sid, None)  # only forget the upload once the transcript is on disk
    convs = transcript_graph.build_recording(sid, turns)  # one recording -> one or more conversations
    built = [c for c in convs if c["extract"]]
    for c in built:
        _enrich(SessionExtract(**c["extract"]), background, sync_enrich)
    first = (built or convs or [{"graph_status": "no_person", "extract": None}])[0]
    return ProcessResult(session_id=sid, transcript=text, graph_status=first["graph_status"], extract=first["extract"],
                         conversations=convs)


@router.get("")
def list_sessions():
    return queries.sessions(settings.USER_ID)


@router.get("/{sid}")
def get_session(sid: str):
    out = queries.session_detail(settings.USER_ID, sid)
    if out is None:
        raise HTTPException(404, f"session {sid} not found")
    return out

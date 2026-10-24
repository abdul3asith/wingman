"""POST /sessions, POST /sessions/{id}/process — OWNER: Person A."""
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.config import settings
from app.contract import SessionExtract
from app.graph import enrich, queries, writes
from app.ingest import extract as extract_mod
from app.ingest import transcribe
from app.ingest.deepgram import TranscriptionError

router = APIRouter(prefix="/sessions", tags=["ingest"])

# Uploaded-but-unprocessed sessions. Process writes everything to the graph, so this can stay in memory.
_pending: dict[str, dict] = {}


@router.post("")
async def create_session(audio: UploadFile | None = File(None), transcript: str | None = Form(None)):
    """Upload an audio blob (MediaRecorder webm) OR a raw transcript. Returns the session id."""
    if audio is None and not transcript:
        raise HTTPException(400, "send `audio` (multipart file) or `transcript` (form field)")
    sid = "s_" + uuid4().hex[:8]
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
    x = extract_mod.extract(sid, text)
    writes.ingest_session(settings.USER_ID, x)
    _pending.pop(sid, None)  # only forget the upload once it is safely in the graph
    if x.company:
        if sync_enrich:
            enrich.enrich_company(x.company.name, x.company.domain)
        else:
            background.add_task(enrich.enrich_company, x.company.name, x.company.domain)
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

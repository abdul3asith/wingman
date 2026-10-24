"""POST /sessions, POST /sessions/{id}/process — OWNER: Person A."""
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.graph import queries
from app.ingest import transcribe, transcript_graph
from app.ingest.deepgram import TranscriptionError
from app.ingest.turns import to_text

router = APIRouter(prefix="/sessions", tags=["ingest"])

# Uploaded-but-unprocessed sessions. Process saves the transcript to disk, so this can stay in memory.
_pending: dict[str, dict] = {}


class ProcessResult(BaseModel):
    """Response of /process. Ingest-local on purpose: contract.py is frozen and this never crosses the A/B seam."""

    session_id: str
    transcript: str
    graph_status: str


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
        # Stream to disk in chunks: an hour of opus at 32 kbps is ~15 MB, no need to hold it in memory.
        with audio_path.open("wb") as f:
            while chunk := await audio.read(1 << 20):
                f.write(chunk)
    _pending[sid] = {"audio_path": str(audio_path) if audio_path else None, "transcript": transcript}
    return {"session_id": sid, "status": "uploaded", "has_audio": audio_path is not None}


@router.post("/{sid}/process", response_model=ProcessResult)
def process_session(sid: str):
    """Transcribe (or take the pasted text) -> save to cache/transcripts -> graph conversion (stub for now)."""
    pending = _pending.get(sid)
    if pending is None:
        raise HTTPException(404, f"session {sid} not found or already processed")
    try:
        text = pending["transcript"] or to_text(transcribe.transcribe_file(pending["audio_path"]))
    except TranscriptionError as e:
        # Keep the upload pending so the user can retry /process.
        raise HTTPException(502, str(e))
    out = settings.CACHE_DIR / "transcripts" / f"{sid}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    _pending.pop(sid, None)  # only forget the upload once the transcript is on disk
    return ProcessResult(session_id=sid, transcript=text, graph_status=transcript_graph.build(sid, text))


@router.get("")
def list_sessions():
    return queries.sessions(settings.USER_ID)


@router.get("/{sid}")
def get_session(sid: str):
    out = queries.session_detail(settings.USER_ID, sid)
    if out is None:
        raise HTTPException(404, f"session {sid} not found")
    return out

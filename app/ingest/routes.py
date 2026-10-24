"""POST /sessions, POST /sessions/{id}/process — OWNER: Person A."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import settings
from app.graph import queries
from app.ingest import transcribe
from app.ingest.deepgram import TranscriptionError
from app.ingest.turns import parse_text, to_text
from app.memory import build as memory
from app.memory.extract import LLMError

router = APIRouter(prefix="/sessions", tags=["ingest"])

# Uploaded-but-unprocessed sessions. Process saves the transcript to disk, so this can stay in memory.
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
        # Stream to disk in chunks: an hour of opus at 32 kbps is ~15 MB, no need to hold it in memory.
        with audio_path.open("wb") as f:
            while chunk := await audio.read(1 << 20):
                f.write(chunk)
    _pending[sid] = {
        "audio_path": str(audio_path) if audio_path else None,
        "transcript": transcript,
        "uploaded_at": datetime.now(timezone.utc),
    }
    return {"session_id": sid, "status": "uploaded", "has_audio": audio_path is not None}


@router.post("/{sid}/process")
def process_session(sid: str):
    """Turns (transcribed or pasted) -> cache/transcripts/<id>.txt -> segment, extract and write event memory.

    Returns {session_id, me_speaker, goal, conversations}. The transcript stays on disk and in this response;
    it is never written to the graph.
    """
    pending = _pending.get(sid)
    if pending is None:
        raise HTTPException(404, f"session {sid} not found or already processed")
    turns = pending.get("turns")
    if turns is None:
        try:
            turns = parse_text(pending["transcript"]) if pending["transcript"] else transcribe.transcribe_file(pending["audio_path"])
        except TranscriptionError as e:
            # Keep the upload pending so the user can retry /process.
            raise HTTPException(502, str(e))
        pending["turns"] = turns  # a retry after an LLM failure skips re-transcribing
    out = settings.CACHE_DIR / "transcripts" / f"{sid}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_text(turns))
    try:
        result = memory.build(sid, turns, uploaded_at=pending.get("uploaded_at"))
    except LLMError as e:
        raise HTTPException(502, str(e))  # session stays pending; retry /process
    _pending.pop(sid, None)  # only forget the upload once its memory is in the graph
    return result


@router.get("")
def list_sessions():
    return queries.sessions(settings.USER_ID)


@router.get("/{sid}")
def get_session(sid: str):
    out = queries.session_detail(settings.USER_ID, sid)
    if out is None:
        raise HTTPException(404, f"session {sid} not found")
    return out

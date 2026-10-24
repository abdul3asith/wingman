"""/agent/* — the voice agent. OWNER: Person A."""
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app import llm
from app.agent import brain, intel
from app.config import settings
from app.ingest import deepgram

router = APIRouter(prefix="/agent", tags=["agent"])
TTS_MODEL = "gpt-4o-mini-tts"
TTS_VOICE = "coral"


class SpeakRequest(BaseModel):
    text: str


class ResearchRequest(BaseModel):
    name: str


def _transcribe_command(path: str) -> str:
    """Push-to-talk is one speaker: Deepgram without diarization when configured (fast), else OpenAI."""
    if settings.DEEPGRAM_API_KEY:
        try:
            return deepgram.transcribe_prerecorded(path, diarize=False)
        except Exception as e:
            print(f"[agent] Deepgram failed ({e}); falling back to OpenAI")
    return llm.transcribe(path).strip()


@router.post("/talk")
async def talk(audio: UploadFile | None = File(None), text: str | None = Form(None), conversation_id: str | None = Form(None)):
    """Push-to-talk: audio (webm from MediaRecorder) or text in -> what we heard, the reply, and UI events."""
    cid = conversation_id or uuid4().hex[:10]
    heard = (text or "").strip()
    if audio is not None and not heard:
        suffix = Path(audio.filename or "talk.webm").suffix or ".webm"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(await audio.read())
        try:
            heard = _transcribe_command(f.name)
        except Exception as e:
            raise HTTPException(502, f"couldn't transcribe that: {e}")
        finally:
            Path(f.name).unlink(missing_ok=True)
    if not heard:
        raise HTTPException(400, "I didn't catch anything — hold the button and speak")
    out = brain.talk(cid, heard)
    return {"conversation_id": cid, "heard": heard, **out}


@router.post("/speak")
def speak(req: SpeakRequest):
    """Text -> mp3 for the agent's voice. The page falls back to the browser's voice if this fails."""
    if not settings.OPENAI_API_KEY:
        raise HTTPException(503, "no OPENAI_API_KEY")
    res = llm.client().audio.speech.create(model=TTS_MODEL, voice=TTS_VOICE, input=req.text[:1200],
                                          instructions="Warm, upbeat, concise. Like a sharp chief of staff.")
    return Response(content=res.read(), media_type="audio/mpeg")


@router.get("/state")
def state():
    return brain.state()


@router.post("/research")
def research(req: ResearchRequest):
    return intel.research(req.name)


@router.get("/why/{draft_id}")
def why(draft_id: str):
    """Full 'why this ask?' path: graph why_path + facts, cited post, portfolio links, goal."""
    from app.agent import why as why_mod

    out = why_mod.why(draft_id)
    if not out:
        raise HTTPException(404, f"draft {draft_id} not found")
    return out


@router.get("/company/{name}")
def company(name: str):
    """Company intel as it stands now; the page polls this while the Crunchbase portfolio job runs."""
    from app.agent import store

    return {"company": name, **store.company_intel(name)}

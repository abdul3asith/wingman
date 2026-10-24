"""Audio -> transcript. OWNER: Person A.

Order: MOCK_MODE (or no file) -> canned two-speaker transcript; DEEPGRAM_API_KEY set -> Deepgram nova-3 with
speaker labels; otherwise OpenAI gpt-4o-transcribe (unlabeled text).
"""
from app import llm
from app.config import settings
from app.ingest import deepgram

# Mock-mode transcript: a short two-speaker conversation in the same "Speaker N:" format Deepgram produces.
MOCK_TRANSCRIPT = (
    "Speaker 0: Hey, I'm Maya Lindqvist, I'm an ML engineer at Parallax Labs. What are you working on?\n"
    "Speaker 1: Mostly GPU inference. I've been benchmarking CUDA graph capture to cut launch overhead.\n"
    "Speaker 0: Nice. We run a small draft model in front of the big one for speculative decoding and got about "
    "a two x speedup. We're hiring an inference engineer, I can refer you if you're interested.\n"
    "Speaker 1: I'd love that. Could you send me the speculative decoding blog post you mentioned?\n"
    "Speaker 0: Sure, I'll send you the blog post. And send me your CUDA benchmark repo.\n"
    "Speaker 1: Will do, I'll send over my CUDA benchmark repo tonight. What's your email?\n"
    "Speaker 0: It's maya at parallaxlabs dot ai."
)


FALLBACK_MODEL = "whisper-1"


def transcribe_file(path: str | None) -> str:
    if settings.MOCK_MODE or not path:
        return MOCK_TRANSCRIPT
    if settings.DEEPGRAM_API_KEY:
        try:
            return deepgram.transcribe_prerecorded(path)
        except Exception as e:  # demo insurance: an unlabeled transcript beats no transcript
            print(f"[transcribe] Deepgram failed ({e}); falling back to OpenAI")
    try:
        return llm.transcribe(path)
    except Exception as e:
        print(f"[transcribe] {settings.OPENAI_STT_MODEL} failed ({e}); retrying with {FALLBACK_MODEL}")
    try:
        return llm.transcribe(path, model=FALLBACK_MODEL)
    except Exception as e:
        raise deepgram.TranscriptionError(f"all transcription backends failed (last: {FALLBACK_MODEL}: {e})") from e

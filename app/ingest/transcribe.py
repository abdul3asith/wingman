"""Audio -> transcript. OWNER: Person A.

Order: MOCK_MODE (or no file) -> canned two-speaker transcript; DEEPGRAM_API_KEY set -> Deepgram nova-3 with
speaker labels; otherwise OpenAI gpt-4o-transcribe (unlabeled text).
"""
from app import llm
from app.config import settings
from app.ingest import deepgram

# Mirrors MOCK_EXTRACT in extract.py: same person, company, topics, promises and spoken email.
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


def transcribe_file(path: str | None) -> str:
    if settings.MOCK_MODE or not path:
        return MOCK_TRANSCRIPT
    if settings.DEEPGRAM_API_KEY:
        return deepgram.transcribe_prerecorded(path)
    return llm.transcribe(path)

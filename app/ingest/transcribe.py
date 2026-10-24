"""Audio -> transcript. OWNER: Person A."""
from app import llm
from app.config import settings

MOCK_TRANSCRIPT = (
    "Okay, just finished talking to Maya Lindqvist, she's an ML engineer at Parallax Labs. We geeked out about "
    "speculative decoding, she said they run a small draft model in front of their big one and got like a two x "
    "speedup on GPU inference, and we compared notes on CUDA graph capture. She asked if I'd be interested in "
    "their inference engineer role and said she can refer me. She's going to send me their speculative decoding "
    "blog post, and I told her I'd send over my CUDA benchmark repo. Her email is maya at parallaxlabs dot ai."
)


def transcribe_file(path: str | None) -> str:
    if settings.MOCK_MODE or not path:
        return MOCK_TRANSCRIPT
    return llm.transcribe(path)

"""Deepgram pre-recorded transcription with speaker diarization. OWNER: Person A.

Plain httpx against https://api.deepgram.com/v1/listen (no SDK). Returns a speaker-labeled transcript:

    Speaker 0: Hi, I'm Maya ...
    Speaker 1: Nice to meet you ...
"""
from pathlib import Path

import httpx

from app.config import settings

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
TIMEOUT_S = 120.0

_CONTENT_TYPES = {
    ".webm": "audio/webm",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
}


class TranscriptionError(Exception):
    """Deepgram returned a non-2xx response. The message never contains the API key."""


def _content_type(path: str) -> str:
    return _CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def transcribe_prerecorded(path: str, client: httpx.Client | None = None) -> str:
    """POST the file's bytes to Deepgram and return a 'Speaker N: ...' transcript.

    `client` is a test seam (httpx.MockTransport); production callers leave it None.
    """
    if not settings.DEEPGRAM_API_KEY:
        raise TranscriptionError("DEEPGRAM_API_KEY is not set")
    # Deepgram docs: `diarize=true` is deprecated; `diarize_model` enables diarization on its own.
    params = {
        "model": settings.DEEPGRAM_MODEL,
        "diarize_model": "latest",
        "smart_format": "true",
        "punctuate": "true",
        "utterances": "true",
    }
    headers = {"Authorization": f"Token {settings.DEEPGRAM_API_KEY}", "Content-Type": _content_type(path)}
    data = Path(path).read_bytes()

    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        res = c.post(DEEPGRAM_URL, params=params, headers=headers, content=data)
    finally:
        if own:
            c.close()
    if res.status_code // 100 != 2:
        raise TranscriptionError(f"Deepgram returned {res.status_code}: {res.text[:500]}")
    utterances = (res.json().get("results") or {}).get("utterances") or []
    return format_utterances(utterances)


def format_utterances(utterances: list[dict]) -> str:
    """Sort by start, drop empty utterances, merge consecutive same-speaker turns, one 'Speaker N: ...' per line."""
    lines: list[list] = []  # [speaker, text]
    for u in sorted(utterances, key=lambda u: u.get("start", 0.0)):
        text = (u.get("transcript") or "").strip()
        if not text:
            continue
        speaker = u.get("speaker", 0)
        if lines and lines[-1][0] == speaker:
            lines[-1][1] += " " + text
        else:
            lines.append([speaker, text])
    return "\n".join(f"Speaker {s}: {t}" for s, t in lines)

"""Deepgram pre-recorded transcription with speaker diarization. OWNER: Person A.

Plain httpx against https://api.deepgram.com/v1/listen (no SDK). Returns a speaker-labeled transcript:

    Speaker 0: Hi, I'm Maya ...
    Speaker 1: Nice to meet you ...

Speaker turns come from word-level `speaker` labels, not from `results.utterances`: Deepgram splits utterances
at pauses, so quick back-and-forth lands in one utterance carrying a single speaker label.
"""
from pathlib import Path

import httpx

from app.config import settings
from app.ingest.turns import Turn, to_text

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
# Deepgram's pre-recorded limit (developers.deepgram.com/docs/pre-recorded-audio, "Limits"): requests exceeding
# 10 minutes of processing on Nova/Base/Enhanced return 504, so waiting longer than that buys nothing.
TIMEOUT_S = 600.0

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


def transcribe_prerecorded(path: str, client: httpx.Client | None = None, diarize: bool = True) -> str:
    """POST the file's bytes to Deepgram and return a 'Speaker N: ...' transcript.

    diarize=False (the voice agent's push-to-talk: one speaker) returns plain text with no speaker labels.
    `client` is a test seam (httpx.MockTransport); production callers leave it None.
    """
    if not settings.DEEPGRAM_API_KEY:
        raise TranscriptionError("DEEPGRAM_API_KEY is not set")
    params = {
        "model": settings.DEEPGRAM_MODEL,
        "smart_format": "true",
        "punctuate": "true",
    }
    if diarize:
        # Deepgram docs: `diarize=true` is deprecated; `diarize_model` enables diarization on its own.
        params["diarize_model"] = "latest"
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
    channels = (res.json().get("results") or {}).get("channels") or []
    alternatives = (channels[0].get("alternatives") if channels else None) or []
    if not diarize:
        return ((alternatives[0].get("transcript") if alternatives else None) or "").strip()
    words = (alternatives[0].get("words") if alternatives else None) or []
    if words and not any("speaker" in w for w in words):
        print("[deepgram] WARNING: no speaker labels in response; everything will read as Speaker 0")
    return format_words(words)


def words_to_turns(words: list[dict]) -> list[Turn]:
    """Word-level `speaker` labels -> one timed Turn per speaker turn (used by app.memory segmentation).

    Words are sorted by `start`; `punctuated_word` is preferred over `word`; empty words are skipped.
    A turn starts at its first word's `start` and ends at its last word's `end`.
    """
    turns: list[Turn] = []
    for w in sorted(words, key=lambda w: w.get("start", 0.0)):
        text = (w.get("punctuated_word") or w.get("word") or "").strip()
        if not text:
            continue
        speaker = int(w.get("speaker", 0))
        start, end = w.get("start"), w.get("end", w.get("start"))
        if turns and turns[-1].speaker == speaker:
            turns[-1].text += " " + text
            turns[-1].end = end
        else:
            turns.append(Turn(speaker=speaker, text=text, start=start, end=end))
    return turns


def format_words(words: list[dict]) -> str:
    """Word-level `speaker` labels -> one 'Speaker N: ...' line per speaker turn. No words -> empty string."""
    return to_text(words_to_turns(words))

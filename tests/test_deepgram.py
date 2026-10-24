import httpx
import pytest

from app.config import settings
from app.ingest import deepgram
from app.ingest.deepgram import TranscriptionError, format_utterances


def _u(speaker, transcript, start):
    return {"speaker": speaker, "transcript": transcript, "start": start, "end": start + 1.0}


def test_format_merges_consecutive_same_speaker():
    out = format_utterances([_u(0, "Hi there.", 0.0), _u(0, "I'm Maya.", 1.0), _u(1, "Hey Maya.", 2.0)])
    assert out == "Speaker 0: Hi there. I'm Maya.\nSpeaker 1: Hey Maya."


def test_format_orders_by_start():
    out = format_utterances([_u(1, "second", 5.0), _u(0, "first", 0.0)])
    assert out == "Speaker 0: first\nSpeaker 1: second"


def test_format_skips_empty_utterances():
    out = format_utterances([_u(0, "hello", 0.0), _u(1, "   ", 1.0), _u(1, "", 2.0), _u(0, "again", 3.0)])
    assert out == "Speaker 0: hello again"


def test_format_empty_input():
    assert format_utterances([]) == ""


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(settings, "DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(settings, "DEEPGRAM_MODEL", "nova-3")


@pytest.fixture
def wav(tmp_path):
    p = tmp_path / "clip.wav"
    p.write_bytes(b"RIFF....WAVEfake")
    return str(p)


def test_transcribe_prerecorded_success(key, wav):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        seen["headers"] = request.headers
        seen["body"] = request.content
        body = {"results": {"utterances": [_u(0, "Hi, I'm Sarah.", 0.0), _u(1, "Hi Sarah.", 2.0)]}}
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = deepgram.transcribe_prerecorded(wav, client=c)

    assert out == "Speaker 0: Hi, I'm Sarah.\nSpeaker 1: Hi Sarah."
    q = dict(seen["url"].params)
    assert seen["url"].host == "api.deepgram.com" and seen["url"].path == "/v1/listen"
    assert q == {"model": "nova-3", "diarize_model": "latest", "smart_format": "true", "punctuate": "true", "utterances": "true"}
    assert seen["headers"]["authorization"] == "Token test-key"
    assert seen["headers"]["content-type"] == "audio/wav"
    assert seen["body"] == b"RIFF....WAVEfake"


def test_transcribe_prerecorded_4xx_raises(key, wav):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"err_code": "INVALID_AUTH", "err_msg": "Invalid credentials."})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(TranscriptionError) as ei:
            deepgram.transcribe_prerecorded(wav, client=c)
    msg = str(ei.value)
    assert "401" in msg and "INVALID_AUTH" in msg
    assert "test-key" not in msg

import httpx
import pytest

from app.config import settings
from app.ingest import deepgram
from app.ingest.deepgram import TranscriptionError, format_words, words_to_turns
from app.ingest.turns import Turn, to_text


def _w(speaker, word, start, punctuated=None):
    out = {"speaker": speaker, "word": word, "start": start, "end": start + 0.2}
    if punctuated is not None:
        out["punctuated_word"] = punctuated
    return out


def test_format_new_line_on_speaker_change_and_prefers_punctuated_word():
    words = [_w(0, "hi", 0.0, "Hi,"), _w(0, "there", 0.3, "there."), _w(1, "hey", 0.6, "Hey."), _w(1, "maya", 0.9)]
    assert format_words(words) == "Speaker 0: Hi, there.\nSpeaker 1: Hey. maya"


def test_format_orders_by_start():
    words = [_w(1, "second", 5.0), _w(0, "first", 0.0)]
    assert format_words(words) == "Speaker 0: first\nSpeaker 1: second"


def test_format_skips_empty_words():
    words = [_w(0, "hello", 0.0), _w(1, "   ", 0.3), _w(1, "", 0.6, ""), _w(0, "again", 0.9)]
    assert format_words(words) == "Speaker 0: hello again"


def test_format_empty_input():
    assert format_words([]) == ""


def test_format_fast_turn_taking_inside_one_utterance():
    # Quick back-and-forth with no pauses: Deepgram puts this in ONE utterance labeled speaker 0,
    # but the word-level labels alternate. The formatter must follow the words.
    words = [
        _w(0, "ready", 0.0, "Ready?"),
        _w(1, "yes", 0.2, "Yes."),
        _w(0, "go", 0.4, "Go."),
        _w(1, "okay", 0.6, "Okay,"),
        _w(1, "going", 0.8, "going."),
        _w(0, "nice", 1.0, "Nice."),
    ]
    assert format_words(words) == (
        "Speaker 0: Ready?\nSpeaker 1: Yes.\nSpeaker 0: Go.\nSpeaker 1: Okay, going.\nSpeaker 0: Nice."
    )


def test_words_to_turns_carries_first_start_and_last_end():
    words = [_w(0, "hi", 0.0, "Hi,"), _w(0, "there", 0.3, "there."), _w(1, "hey", 1.5, "Hey.")]
    assert words_to_turns(words) == [Turn(0, "Hi, there.", 0.0, 0.5), Turn(1, "Hey.", 1.5, 1.7)]


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
        words = [_w(0, "hi", 0.0, "Hi,"), _w(0, "sarah", 0.2, "Sarah."), _w(1, "hi", 0.5, "Hi.")]
        body = {"results": {"channels": [{"alternatives": [{"transcript": "Hi, Sarah. Hi.", "words": words}]}]}}
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = deepgram.transcribe_prerecorded(wav, client=c)

    # The app's transcribe path returns speaker-labeled text; timed turns come from words_to_turns (tested above).
    assert out == "Speaker 0: Hi, Sarah.\nSpeaker 1: Hi."
    q = dict(seen["url"].params)
    assert seen["url"].host == "api.deepgram.com" and seen["url"].path == "/v1/listen"
    assert q == {"model": "nova-3", "diarize_model": "latest", "smart_format": "true", "punctuate": "true"}
    assert seen["headers"]["authorization"] == "Token test-key"
    assert seen["headers"]["content-type"] == "audio/wav"
    assert seen["body"] == b"RIFF....WAVEfake"


def test_transcribe_prerecorded_without_diarization_returns_plain_text(key, wav):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        body = {"results": {"channels": [{"alternatives": [{"transcript": " Who fits my goals? ", "words": []}]}]}}
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out = deepgram.transcribe_prerecorded(wav, client=c, diarize=False)

    assert out == "Who fits my goals?"
    assert "diarize_model" not in seen["params"]


def test_transcribe_prerecorded_4xx_raises(key, wav):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"err_code": "INVALID_AUTH", "err_msg": "Invalid credentials."})

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(TranscriptionError) as ei:
            deepgram.transcribe_prerecorded(wav, client=c)
    msg = str(ei.value)
    assert "401" in msg and "INVALID_AUTH" in msg
    assert "test-key" not in msg

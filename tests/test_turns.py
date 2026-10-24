from app.ingest.turns import Turn, parse_text, to_text


def test_parse_speaker_lines_into_turns_without_timings():
    text = "Speaker 0: Hi, I'm Maya.\nSpeaker 1: Nice to meet you.\n\nSpeaker 0: Likewise."
    assert parse_text(text) == [Turn(0, "Hi, I'm Maya."), Turn(1, "Nice to meet you."), Turn(0, "Likewise.")]
    assert all(t.start is None and t.end is None for t in parse_text(text))


def test_parse_merges_same_speaker_and_continuation_lines():
    text = "Speaker 2: first part\nsecond part\nSpeaker 2: third part"
    assert parse_text(text) == [Turn(2, "first part second part third part")]


def test_parse_unlabeled_text_is_speaker_zero():
    assert parse_text("smoke test transcript") == [Turn(0, "smoke test transcript")]
    assert parse_text("") == []


def test_to_text_labels_me_as_you():
    turns = [Turn(0, "Hi."), Turn(1, "Hello.")]
    assert to_text(turns) == "Speaker 0: Hi.\nSpeaker 1: Hello."
    assert to_text(turns, me=1) == "Speaker 0: Hi.\nYou: Hello."

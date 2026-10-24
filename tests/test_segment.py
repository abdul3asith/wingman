from app.ingest.transcribe import MOCK_TURNS
from app.ingest.turns import Turn
from app.memory.segment import GAP_S, SWITCH_S, identify_me, split_conversations

LONG = "one two three four five six seven eight nine ten"  # 10 words: above MIN_WORDS


def T(speaker, start, dur=4.0, text=LONG):
    return Turn(speaker, text, start, start + dur)


def _speakers(conv):
    return [t.speaker for t in conv.turns]


def test_two_conversations_separated_by_gap():
    turns = [T(1, 0), T(0, 5), T(1, 10), T(2, 14 + GAP_S + 1), T(1, 14 + GAP_S + 6)]
    convs = split_conversations(turns, me=1)
    assert len(convs) == 2
    assert convs[0].partners == [0] and convs[1].partners == [2]
    assert (convs[0].start, convs[0].end) == (0, 14)
    assert [c.seq for c in convs] == [1, 2]


def test_partner_switch_without_gap():
    # Speaker 0 last speaks at 9..13; speaker 2 starts 3 s after the user's closing line (no GAP_S silence),
    # and more than SWITCH_S after speaker 0's last turn.
    turns = [T(0, 0), T(1, 5), T(0, 9), T(1, 14, dur=2), T(2, 13 + SWITCH_S + 3), T(1, 30), T(2, 35)]
    convs = split_conversations(turns, me=1)
    assert len(convs) == 2
    assert _speakers(convs[0]) == [0, 1, 0, 1]
    assert convs[1].partners == [2]


def test_group_conversation_stays_one():
    turns = [T(0, 0), T(1, 5), T(2, 10), T(0, 15), T(1, 20), T(2, 25)]
    convs = split_conversations(turns, me=1)
    assert len(convs) == 1
    assert convs[0].partners == [0, 2]


def test_passerby_does_not_split():
    # Speaker 3 says 3 words long after speaker 0 last spoke; under MIN_WORDS, so no split.
    turns = [T(0, 0), T(1, 5), T(1, 10, dur=8), T(3, 19, dur=1, text="excuse me, sorry"), T(0, 21), T(1, 26)]
    convs = split_conversations(turns, me=1)
    assert len(convs) == 1
    assert convs[0].partners == [0, 3]


def test_turns_without_timings():
    turns = [Turn(0, LONG), Turn(1, LONG), Turn(0, LONG), Turn(2, LONG), Turn(1, LONG)]
    assert identify_me([Turn(0, LONG), Turn(1, LONG + " " + LONG)]) == 1  # one chunk: total words decide
    convs = split_conversations(turns, me=1)
    assert len(convs) == 2  # a new significant speaker splits (no SWITCH_S check without timings)
    assert convs[0].start is None and convs[0].end is None
    assert convs[1].partners == [2]


def test_identify_me_by_presence_not_words():
    # Speaker 0 out-talks the user inside conversation 1, but the user (1) is present in both chunks.
    chatty = LONG + " " + LONG + " " + LONG
    turns = [T(0, 0, text=chatty), T(1, 5, text="sure, sounds good"), T(0, 10, text=chatty),
             T(2, 14 + GAP_S + 5), T(1, 45, text="yes")]
    assert identify_me(turns) == 1


def test_mock_recording_has_two_conversations_and_me_is_speaker_1():
    me = identify_me(MOCK_TURNS)
    assert me == 1
    convs = split_conversations(MOCK_TURNS, me)
    assert [c.partners for c in convs] == [[0], [2]]

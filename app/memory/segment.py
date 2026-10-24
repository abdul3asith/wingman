"""Split one recording's speaker turns into conversations. Pure and deterministic: no LLM, no I/O.

One recording can hold several conversations in a row (two minutes with A, then B, ...). The user is in all of
them, which is how `identify_me` finds the user: the speaker present across the most silence-separated chunks.
"""
from collections import defaultdict
from dataclasses import dataclass, field

from app.ingest.turns import Turn

GAP_S = 20.0  # silence (seconds) between consecutive turns that always starts a new chunk / conversation
SWITCH_S = 10.0  # a new partner only starts a new conversation if no current partner spoke in this many seconds
MIN_WORDS = 8  # words across the whole recording for a speaker to count as a conversation partner (not a passerby)


@dataclass
class Conversation:
    seq: int
    start: float | None
    end: float | None
    turns: list[Turn] = field(default_factory=list)
    partners: list[int] = field(default_factory=list)  # non-me speakers in this conversation, in order of appearance


def _gap(prev: Turn, nxt: Turn) -> float | None:
    if prev.end is None or nxt.start is None:
        return None
    return nxt.start - prev.end


def _word_counts(turns: list[Turn]) -> dict[int, int]:
    words: dict[int, int] = defaultdict(int)
    for t in turns:
        words[t.speaker] += t.words
    return words


def _chunks(turns: list[Turn]) -> list[list[Turn]]:
    """Split wherever the silence between consecutive turns is at least GAP_S. No timings -> one chunk."""
    chunks: list[list[Turn]] = []
    for t in turns:
        g = _gap(chunks[-1][-1], t) if chunks else None
        if not chunks or (g is not None and g >= GAP_S):
            chunks.append([t])
        else:
            chunks[-1].append(t)
    return chunks


def identify_me(turns: list[Turn]) -> int:
    """The user is the speaker present in the most chunks; ties (and the no-timings case) go to total words."""
    if not turns:
        return 0
    presence: dict[int, int] = defaultdict(int)
    for chunk in _chunks(turns):
        for speaker in {t.speaker for t in chunk}:
            presence[speaker] += 1
    words = _word_counts(turns)
    # Final key (-speaker) makes a full tie deterministic: the lower speaker label wins.
    return max(presence, key=lambda s: (presence[s], words[s], -s))


def split_conversations(turns: list[Turn], me: int) -> list[Conversation]:
    """Cut the turns into conversations.

    A new conversation starts when the silence before a turn is at least GAP_S, or when a significant non-me
    speaker (>= MIN_WORDS words in the whole recording) who isn't a current partner starts talking and none of
    the current significant partners spoke in the last SWITCH_S seconds. Without timings the SWITCH_S check is
    skipped. Speakers under MIN_WORDS never split anything; they stay inside the conversation they appear in.
    """
    words = _word_counts(turns)
    significant = {s for s, n in words.items() if s != me and n >= MIN_WORDS}
    convs: list[Conversation] = []
    last_spoke: dict[int, float | None] = {}  # partner -> end time of their latest turn in the current conversation

    for t in turns:
        cur = convs[-1] if convs else None
        new = cur is None
        if cur is not None:
            g = _gap(cur.turns[-1], t)
            if g is not None and g >= GAP_S:
                new = True
            elif t.speaker in significant and t.speaker not in cur.partners:
                current = [p for p in cur.partners if p in significant]
                if current:  # a partner joining a conversation that has none yet is not a switch
                    if t.start is None:
                        new = True
                    else:
                        recent = any(
                            last_spoke.get(p) is not None and t.start - last_spoke[p] < SWITCH_S for p in current
                        )
                        new = not recent
        if new:
            cur = Conversation(seq=len(convs) + 1, start=t.start, end=t.end)
            convs.append(cur)
            last_spoke = {}
        cur.turns.append(t)
        if t.end is not None:
            cur.end = t.end if cur.end is None else max(cur.end, t.end)
        if cur.start is None and t.start is not None:
            cur.start = t.start
        if t.speaker != me:
            if t.speaker not in cur.partners:
                cur.partners.append(t.speaker)
            last_spoke[t.speaker] = t.end if t.end is not None else t.start
    return convs


def main_partner(conv: Conversation, me: int) -> int | None:
    """The non-me speaker with the most words in this conversation (used for placeholder names)."""
    counts = _word_counts([t for t in conv.turns if t.speaker != me])
    return max(counts, key=lambda s: (counts[s], -s)) if counts else None

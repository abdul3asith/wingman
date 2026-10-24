"""Speaker turns: the structured shape every transcription path returns.

A turn is one uninterrupted stretch of speech by one diarized speaker. Deepgram turns carry start/end seconds;
pasted text parsed from "Speaker N: ..." lines has no timings (start/end are None).
"""
import re
from dataclasses import dataclass

_LINE = re.compile(r"^\s*Speaker\s+(\d+)\s*:\s*(.*)$", re.IGNORECASE)


@dataclass
class Turn:
    speaker: int
    text: str
    start: float | None = None
    end: float | None = None

    @property
    def words(self) -> int:
        return len(self.text.split())


def parse_text(text: str) -> list[Turn]:
    """'Speaker N: ...' lines -> turns without timings.

    A line without a label continues the previous turn; unlabeled text before any label (for example a
    gpt-4o-transcribe result, which has no speakers) becomes speaker 0.
    """
    turns: list[Turn] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LINE.match(line)
        if m:
            speaker, body = int(m.group(1)), m.group(2).strip()
            if turns and turns[-1].speaker == speaker:
                turns[-1].text = f"{turns[-1].text} {body}".strip()
            else:
                turns.append(Turn(speaker=speaker, text=body))
        elif turns:
            turns[-1].text = f"{turns[-1].text} {line}".strip()
        else:
            turns.append(Turn(speaker=0, text=line))
    return [t for t in turns if t.text]


def to_text(turns: list[Turn], me: int | None = None) -> str:
    """Turns -> one 'Speaker N: ...' line per turn. With `me`, that speaker's lines are labeled 'You:'."""
    return "\n".join(f"{'You' if t.speaker == me else f'Speaker {t.speaker}'}: {t.text}" for t in turns)

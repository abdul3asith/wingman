"""Check your Deepgram key end to end: `python scripts/check_deepgram.py` (or `make check-deepgram`).

Builds a short two-voice conversation with macOS `say`, sends it to Deepgram the same way the app does, and prints
the speaker-labeled transcript. PASS means: key works and two different speakers came back.
"""
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.ingest import deepgram  # noqa: E402

LINES = [
    ("Samantha", "Hi, I'm Sarah Chen, I'm a backend engineer at Modal. We're hiring for inference."),
    ("Daniel", "Nice to meet you Sarah. I work on GPU kernels and CUDA benchmarks."),
    ("Samantha", "Find me on LinkedIn, sarah chen. Send me your benchmark repo."),
    ("Daniel", "Will do, I'll send it tonight."),
]


def build_clip(out: Path) -> None:
    tmp = Path(tempfile.mkdtemp())
    parts = []
    for i, (voice, text) in enumerate(LINES):
        p = tmp / f"{i}.wav"
        subprocess.run(["say", "-v", voice, "-o", str(p), "--data-format=LEI16@16000", text], check=True)
        parts.append(p)
    with wave.open(str(out), "wb") as w:
        with wave.open(str(parts[0])) as first:
            w.setparams(first.getparams())
        for p in parts:
            with wave.open(str(p)) as r:
                w.writeframes(r.readframes(r.getnframes()))
                w.writeframes(b"\x00\x00" * 8000)  # half a second of silence between turns


def main() -> int:
    if not settings.DEEPGRAM_API_KEY:
        print("FAIL  DEEPGRAM_API_KEY is empty in .env. Get one at https://console.deepgram.com → API Keys.")
        return 1
    if not shutil.which("say"):
        print("FAIL  this check builds its test clip with macOS `say`")
        return 1
    clip = Path(tempfile.mkdtemp()) / "conversation.wav"
    build_clip(clip)
    t = time.time()
    try:
        out = deepgram.transcribe_prerecorded(str(clip))
    except deepgram.TranscriptionError as e:
        print(f"FAIL  {e}")
        return 1
    print(f"Deepgram {settings.DEEPGRAM_MODEL} answered in {time.time() - t:.1f}s:\n\n{out}\n")
    speakers = {line.split(":")[0] for line in out.splitlines() if line.startswith("Speaker ")}
    if len(speakers) >= 2:
        print(f"PASS  key works, {len(speakers)} speakers labeled")
        return 0
    print("WARN  key works, but only one speaker was labeled (synthetic voices can confuse diarization; try a real chat)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

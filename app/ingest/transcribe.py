"""Audio -> speaker turns. OWNER: Person A.

Order: MOCK_MODE (or no file) -> canned turns holding two conversations; DEEPGRAM_API_KEY set -> Deepgram nova-3
with word-level speaker labels and timings; otherwise OpenAI gpt-4o-transcribe (unlabeled text, one turn, no timings).
"""
from app import llm
from app.config import settings
from app.ingest import deepgram
from app.ingest.turns import Turn, parse_text

# Mock-mode recording: two conversations separated by ~38 s of silence. Speaker 1 is the user in both, so
# segmentation finds "me" by presence across chunks even though Maya and Jordan each talk more.
MOCK_TURNS: list[Turn] = [
    # Conversation 1: Maya Lindqvist, ML engineer at Parallax Labs.
    Turn(0, "Hey, I'm Maya Lindqvist, I'm an ML engineer at Parallax Labs. What are you working on?", 0.0, 5.2),
    Turn(1, "Mostly GPU inference. I've been benchmarking CUDA graph capture to cut launch overhead.", 5.6, 10.4),
    Turn(0, "Nice. We run a small draft model in front of the big one for speculative decoding and got about a two x "
            "speedup. We're hiring an inference engineer, I can refer you if you're interested.", 10.9, 21.5),
    Turn(1, "I'd love that. Could you send me the speculative decoding blog post you mentioned?", 22.0, 26.8),
    Turn(0, "Sure, I'll send you the blog post. And send me your CUDA benchmark repo.", 27.2, 31.9),
    Turn(1, "Will do, I'll send over my CUDA benchmark repo tonight. What's your email?", 32.3, 37.1),
    Turn(0, "It's maya at parallaxlabs dot ai.", 37.5, 40.2),
    # ~38 s of silence, then conversation 2: Jordan Reyes, technical recruiter at Lattice Compute.
    Turn(2, "Hi! I'm Jordan Reyes, I'm a technical recruiter at Lattice Compute. Are you looking for roles right now?",
         78.0, 84.5),
    Turn(1, "I am, actually. I'm looking for a software engineering role, ideally around inference or backend.",
         85.0, 89.6),
    Turn(2, "Great timing. We're hiring backend and inference engineers. The role is fully remote, and the stack is "
            "mostly Python and Go.", 90.1, 101.8),
    Turn(1, "That sounds like a great fit. What does the interview process look like?", 102.3, 105.9),
    Turn(2, "It's three rounds: a recruiter screen, a technical deep dive on systems, and a final round with the team.",
         106.4, 115.0),
    Turn(1, "Perfect. Could you send me the job link?", 115.5, 118.8),
    Turn(2, "Absolutely, I'll send you the job link today. What's the best email for you?", 119.3, 124.6),
    Turn(1, "I'll email you my resume tonight so you have it.", 125.0, 129.2),
]


def transcribe_file(path: str | None) -> list[Turn]:
    if settings.MOCK_MODE or not path:
        return [Turn(t.speaker, t.text, t.start, t.end) for t in MOCK_TURNS]
    if settings.DEEPGRAM_API_KEY:
        return deepgram.transcribe_prerecorded(path)
    return parse_text(llm.transcribe(path))

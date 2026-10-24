"""Thin OpenAI helpers. Callers check settings.MOCK_MODE before calling transcribe/parse;
embed() handles mock mode itself (deterministic vectors) so the graph layer never cares."""
import hashlib
import math
import random
from typing import TypeVar

from pydantic import BaseModel

from app.config import settings

T = TypeVar("T", bound=BaseModel)
_client = None


def client():
    global _client
    if _client is None:
        from openai import OpenAI

        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY not set (or set MOCK_MODE=true)")
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def transcribe(path: str, model: str | None = None) -> str:
    """Speech to text, gpt-4o-transcribe by default."""
    with open(path, "rb") as f:
        res = client().audio.transcriptions.create(model=model or settings.OPENAI_STT_MODEL, file=f)
    return res.text


def parse(prompt: str, model_cls: type[T], system: str = "You are a precise information extractor. Return only the schema.") -> T:
    """Structured output via Pydantic parse. model_cls fields must have no defaults (strict schema)."""
    c = client()
    parser = getattr(c.chat.completions, "parse", None) or c.beta.chat.completions.parse
    res = parser(
        model=settings.OPENAI_CHAT_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        response_format=model_cls,
    )
    parsed = res.choices[0].message.parsed
    if parsed is None:
        raise RuntimeError(f"LLM refused/failed to parse into {model_cls.__name__}")
    return parsed


def embed(text: str) -> list[float]:
    """Topic embedding. Mock mode: deterministic unit vector from a hash (stable across runs)."""
    if settings.MOCK_MODE:
        return _mock_embedding(text)
    res = client().embeddings.create(model=settings.OPENAI_EMBED_MODEL, input=text)
    return res.data[0].embedding


def _mock_embedding(text: str) -> list[float]:
    seed = int(hashlib.sha256(text.strip().lower().encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(settings.EMBED_DIM)]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]

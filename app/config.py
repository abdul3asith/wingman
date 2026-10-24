"""Env loading. Import `settings` everywhere; never read os.environ elsewhere."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key)
    return val if val not in (None, "") else default


def _bool(key: str, default: bool) -> bool:
    val = _env(key)
    return default if val is None else val.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    MOCK_MODE: bool = _bool("MOCK_MODE", True)

    OPENAI_API_KEY: str | None = _env("OPENAI_API_KEY")
    OPENAI_CHAT_MODEL: str = _env("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    OPENAI_STT_MODEL: str = _env("OPENAI_STT_MODEL", "gpt-4o-transcribe")
    OPENAI_EMBED_MODEL: str = _env("OPENAI_EMBED_MODEL", "text-embedding-3-small")
    EMBED_DIM: int = 1536

    BRIGHTDATA_API_KEY: str | None = _env("BRIGHTDATA_API_KEY")
    BRIGHTDATA_SERP_ZONE: str | None = _env("BRIGHTDATA_SERP_ZONE")
    BRIGHTDATA_UNLOCKER_ZONE: str | None = _env("BRIGHTDATA_UNLOCKER_ZONE")

    RESEND_API_KEY: str | None = _env("RESEND_API_KEY")
    FROM_EMAIL: str = _env("FROM_EMAIL", "wingman@example.com")

    FALKORDB_HOST: str = _env("FALKORDB_HOST", "localhost")
    FALKORDB_PORT: int = int(_env("FALKORDB_PORT", "6379"))
    GRAPH_NAME: str = _env("GRAPH_NAME", "wingman")

    USER_ID: str = _env("USER_ID", "me")
    USER_NAME: str = _env("USER_NAME", "Me")
    USER_SKILLS: list[str] = [s.strip() for s in _env("USER_SKILLS", "CUDA,Python,LLM inference").split(",") if s.strip()]
    RESUME_URL: str = _env("RESUME_URL", "https://example.com/resume.pdf")
    DECK_URL: str = _env("DECK_URL", "https://example.com/deck.pdf")
    EVENT_NAME: str = _env("EVENT_NAME", "the conference")

    ROOT: Path = ROOT
    WEB_DIR: Path = ROOT / "web"
    SEED_DIR: Path = ROOT / "seed"
    CACHE_DIR: Path = ROOT / "cache"


settings = Settings()
settings.CACHE_DIR.mkdir(exist_ok=True)
(settings.CACHE_DIR / "pages").mkdir(exist_ok=True)
(settings.CACHE_DIR / "audio").mkdir(exist_ok=True)

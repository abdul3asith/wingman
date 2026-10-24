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

    DEEPGRAM_API_KEY: str | None = _env("DEEPGRAM_API_KEY")
    DEEPGRAM_MODEL: str = _env("DEEPGRAM_MODEL", "nova-3")

    BRIGHTDATA_API_KEY: str | None = _env("BRIGHTDATA_API_KEY")
    BRIGHTDATA_SERP_ZONE: str | None = _env("BRIGHTDATA_SERP_ZONE")
    BRIGHTDATA_UNLOCKER_ZONE: str | None = _env("BRIGHTDATA_UNLOCKER_ZONE")

    RESEND_API_KEY: str | None = _env("RESEND_API_KEY")
    FROM_EMAIL: str = _env("FROM_EMAIL", "wingman@example.com")
    SEND_TEST_TO: str | None = _env("SEND_TEST_TO")  # rehearsal: every approved email goes here instead

    FALKORDB_HOST: str = _env("FALKORDB_HOST", "localhost")
    FALKORDB_PORT: int = int(_env("FALKORDB_PORT", "6379"))
    FALKORDB_UI_PORT: int = int((_env("FALKORDB_UI_PORT", "3000") or "3000").split("#")[0].strip())
    GRAPH_NAME: str = _env("GRAPH_NAME", "wingman")

    USER_ID: str = _env("USER_ID", "me")
    USER_NAME: str = _env("USER_NAME", "Me")
    USER_SKILLS: list[str] = [s.strip() for s in _env("USER_SKILLS", "CUDA,Python,LLM inference").split(",") if s.strip()]
    RESUME_URL: str = _env("RESUME_URL", "https://example.com/resume.pdf")
    DECK_URL: str = _env("DECK_URL", "https://example.com/deck.pdf")
    DEMO_URL: str = _env("DEMO_URL", "https://example.com/demo")
    # Links for things you promise in conversation, matched by keyword: "repo=https://github.com/me/bench,notes=https://..."
    ASSET_LINKS: dict[str, str] = dict(
        kv.split("=", 1) for kv in (_env("ASSET_LINKS", "") or "").split(",") if "=" in kv
    )
    EVENT_NAME: str = _env("EVENT_NAME", "the conference")

    # Demo persona: a startup founder at the conference meeting investors, accelerator partners, founders and hires.
    STARTUP_NAME: str = _env("STARTUP_NAME", "Wingman")
    STARTUP_PITCH: str = _env("STARTUP_PITCH", "a voice-first agent that turns conference conversations into follow-ups")
    STARTUP_STAGE: str = _env("STARTUP_STAGE", "raising our pre-seed")
    HIRING_FOR: str = _env("HIRING_FOR", "founding engineers")
    PERSONA_GOAL: str = _env(
        "PERSONA_GOAL", "Founder at the conference: raise from investors and accelerators, partner with founders, hire early team"
    )

    ROOT: Path = ROOT
    WEB_DIR: Path = ROOT / "web"
    SEED_DIR: Path = ROOT / "seed"
    CACHE_DIR: Path = ROOT / "cache"


settings = Settings()
settings.CACHE_DIR.mkdir(exist_ok=True)
(settings.CACHE_DIR / "pages").mkdir(exist_ok=True)
(settings.CACHE_DIR / "audio").mkdir(exist_ok=True)

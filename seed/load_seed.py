"""Load seed/sessions/*.json and seed/webdocs/*.json into the graph. Idempotent (everything MERGEs).
Run: `make seed` or `python -m seed.load_seed`."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.contract import EnrichResult, SessionExtract  # noqa: E402
from app.graph import schema, writes  # noqa: E402


def load_all() -> dict:
    schema.ensure()
    writes.ensure_user()
    n_sessions = n_webdocs = 0
    for path in sorted((settings.SEED_DIR / "sessions").glob("*.json")):
        writes.ingest_session(settings.USER_ID, SessionExtract(**json.loads(path.read_text())))
        n_sessions += 1
    for path in sorted((settings.SEED_DIR / "webdocs").glob("*.json")):
        writes.write_webdocs(EnrichResult(**json.loads(path.read_text())))
        n_webdocs += 1
    return {"sessions": n_sessions, "webdoc_fixtures": n_webdocs}


if __name__ == "__main__":
    print(load_all())

"""Person A's only doorway into Person B's graph code. OWNER: Person A.

B's spec (claude-b.md) names some signatures differently from the scaffold, e.g.
ingest_session(extract, uid) vs ingest_session(uid, extract), enrich_company(name) vs (name, domain).
Everything in app/ingest and app/asks calls these wrappers, so when B renames things we fix it here once.
"""
import inspect

from app.config import settings
from app.contract import EnrichResult, SessionExtract
from app.graph import enrich, writes


def ingest_session(x: SessionExtract, uid: str = settings.USER_ID) -> None:
    params = list(inspect.signature(writes.ingest_session).parameters)
    if params and params[0] in ("extract", "x", "session"):
        writes.ingest_session(x, uid)  # B's spec order
    else:
        writes.ingest_session(uid, x)  # scaffold order


def enrich_company(name: str, domain: str | None = None) -> EnrichResult:
    if "domain" in inspect.signature(enrich.enrich_company).parameters:
        return enrich.enrich_company(name, domain)
    return enrich.enrich_company(name)  # TODO(B-request): accept an optional domain hint from the debrief

"""Person A's only doorway into Person B's graph code. OWNER: Person A.

B's spec (claude-b.md) names some signatures differently from the scaffold, e.g.
ingest_session(extract, uid) vs ingest_session(uid, extract), enrich_company(name) vs (name, domain),
write_draft(draft, uid, because_refs) vs write_draft(draft). Everything in app/ingest and app/asks calls these
wrappers, so when B renames things we fix it here once.
"""
import inspect

from app.config import settings
from app.contract import CommonGround, Draft, EnrichResult, SessionExtract
from app.graph import enrich, queries, writes


def _params(fn) -> list[str]:
    return list(inspect.signature(fn).parameters)


def _pick(row: dict, *keys, default=None):
    """B's rows may come back aliased ("job_title") or raw ("j.title"); take the first key present."""
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return default


# ---------------------------------------------------------------- writes


def ingest_session(x: SessionExtract, uid: str = settings.USER_ID) -> None:
    params = _params(writes.ingest_session)
    if params and params[0] in ("extract", "x", "session"):
        writes.ingest_session(x, uid)  # B's spec order
    else:
        writes.ingest_session(uid, x)  # scaffold order


def enrich_company(name: str, domain: str | None = None) -> EnrichResult:
    if "domain" in _params(enrich.enrich_company):
        return enrich.enrich_company(name, domain)
    return enrich.enrich_company(name)  # TODO(B-request): accept an optional domain hint from the debrief


def write_draft(d: Draft, uid: str = settings.USER_ID) -> None:
    if "because_refs" in _params(writes.write_draft):
        writes.write_draft(d, uid, d.because)  # B's spec
    else:
        writes.write_draft(d)  # scaffold reads d.because


def set_draft_status(draft_id: str, status: str) -> None:
    writes.set_draft_status(draft_id, status)  # TODO(B-request): keep set_draft_status(id, status) in writes.py


# ---------------------------------------------------------------- reads


def common_ground(uid: str = settings.USER_ID, person: str | None = None) -> list[CommonGround]:
    rows = queries.common_ground(uid, person)
    return [r if isinstance(r, CommonGround) else CommonGround(
        person=_pick(r, "person", "p.name"), company=_pick(r, "company", "c.name"), topic=_pick(r, "topic", "t.name"),
        doc_title=_pick(r, "doc_title", "d.title"), doc_url=_pick(r, "doc_url", "d.url"), doc_kind=_pick(r, "doc_kind", "d.kind", default="site"),
    ) for r in rows]


def referral_radar(uid: str = settings.USER_ID) -> list[dict]:
    """Normalized: person, company, job_title, job_url, matched (list[str]), score."""
    out = []
    for r in queries.referral_radar(uid):
        matched = _pick(r, "matched", "matched_skills", default=[])
        out.append({
            "person": _pick(r, "person", "p.name"), "company": _pick(r, "company", "c.name"),
            "job_title": _pick(r, "job_title", "j.title"), "job_url": _pick(r, "job_url", "j.url"),
            "matched": matched, "score": _pick(r, "score", default=len(matched)),
        })
    return sorted(out, key=lambda r: -r["score"])


def people(uid: str = settings.USER_ID) -> list[dict]:
    """Everyone met: name, role, role_class, email, company, topics."""
    return queries.people(uid)  # TODO(B-request): keep queries.people(uid) — not in claude-b.md's interface list


def open_promises(uid: str = settings.USER_ID) -> list[dict]:
    """Open promises: person, by, text, session_id."""
    return queries.open_promises(uid)  # TODO(B-request): keep queries.open_promises(uid) (also backs the preset)


def draft_queue(status: str | None) -> list[Draft]:
    return queries.draft_queue(status)  # TODO(B-request): keep draft_queue(status) / get_draft(id)


def get_draft(draft_id: str) -> Draft | None:
    return queries.get_draft(draft_id)

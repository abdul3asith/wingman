"""People intel via Bright Data — the agent's live senses. OWNER: Person A.

For one person we met:
  1. LinkedIn URL: the handle they said in the conversation, else SERP `site:linkedin.com/in "<name>" "<company>"`.
  2. LinkedIn profile + recent posts: Bright Data Datasets API (LinkedIn people profiles, sync scrape).
  3. Company news from the past 7 days: SERP Google News with tbs=qdr:w.
Results land in the graph (store.save_intel) and give drafts a "why now" hook.

Fallbacks: if Bright Data isn't reachable (zone missing, account inactive) we mark it unavailable for a few minutes
so the voice agent never waits on it twice. Canned intel exists ONLY for the fictional seed people (demo data);
real people get nothing rather than invented posts.

TODO(verify): LinkedIn dataset id + response field names against the Bright Data dashboard.
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

import httpx
from pydantic import BaseModel

from app.config import settings
from app.agent import store
from app.graph.db import run

API = "https://api.brightdata.com"
LINKEDIN_DATASET = os.getenv("BRIGHTDATA_LINKEDIN_DATASET", "gd_l1viktl72bvl7bjuj0")  # LinkedIn people profiles
TIMEOUT = 45.0
# Circuit breaker per Bright Data product, so a missing SERP zone doesn't block the LinkedIn dataset.
_down_until: dict[str, float] = {"serp": 0.0, "datasets": 0.0}
_last_error: dict[str, str] = {}


def status() -> dict:
    up = {k: time.time() >= v for k, v in _down_until.items()}
    return {"available": any(up.values()), "services": up, "last_error": "; ".join(f"{k}: {v}" for k, v in _last_error.items())}


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.BRIGHTDATA_API_KEY}", "Content-Type": "application/json"}


def _mark_down(service: str, err: str) -> None:
    _down_until[service], _last_error[service] = time.time() + 300, err[:160]
    print(f"[intel] Bright Data {service} unavailable for 5 min: {err[:160]}")


def _live(service: str) -> bool:
    return not settings.MOCK_MODE and bool(settings.BRIGHTDATA_API_KEY) and time.time() >= _down_until[service]


def _serp(query: str, extra: str = "") -> dict:
    url = f"https://www.google.com/search?q={quote_plus(query)}{extra}&brd_json=1"
    r = httpx.post(f"{API}/request", headers=_headers(), timeout=TIMEOUT,
                   json={"zone": settings.BRIGHTDATA_SERP_ZONE, "url": url, "format": "raw"})
    if r.status_code != 200:
        raise RuntimeError(f"SERP {r.status_code}: {r.text[:120]}")
    return r.json()


# ---------------------------------------------------------------- the three Bright Data calls


def find_linkedin(name: str, company: str | None) -> str | None:
    data = _serp(f'site:linkedin.com/in "{name}"' + (f' "{company}"' if company else ""))
    for item in data.get("organic", []):
        link = item.get("link") or ""
        if re.match(r"https?://([a-z]{2,3}\.)?linkedin\.com/in/", link):
            return link.split("?")[0]
    return None


def linkedin_profile(url: str) -> dict:
    r = httpx.post(f"{API}/datasets/v3/scrape?dataset_id={LINKEDIN_DATASET}&format=json", headers=_headers(),
                   timeout=TIMEOUT, json={"input": [{"url": url}]})
    if r.status_code != 200:
        raise RuntimeError(f"LinkedIn dataset {r.status_code}: {r.text[:120]}")
    d = r.json()
    d = d[0] if isinstance(d, list) and d else d
    if not isinstance(d, dict) or "snapshot_id" in d:  # sync window exceeded: Bright Data handed back a job id
        return {"url": url, "headline": None, "posts": []}
    posts = []
    # activity = what they shared/posted recently (freshest, undated); posts = their own articles (dated)
    for p in (d.get("activity") or [])[:3] + (d.get("posts") or [])[:3]:
        text = p.get("title") or p.get("text") or p.get("attribution") or ""
        link = p.get("link") or p.get("url")
        if text and link:
            posts.append({"url": link, "text": text[:280], "posted_at": (p.get("created_at") or "")[:10] or None, "source": "linkedin"})
    company = d.get("current_company") if isinstance(d.get("current_company"), dict) else {}
    return {
        "url": d.get("url") or url,
        "headline": d.get("position") or d.get("headline") or company.get("title"),
        "posts": posts[:4],
    }


def fresh_news(company: str) -> list[dict]:
    data = _serp(f'"{company}"', "&tbm=nws&tbs=qdr:w")
    items = data.get("news") or data.get("organic") or []
    out = []
    for n in items[:4]:
        if n.get("link") and n.get("title"):
            out.append({"url": n["link"], "title": n["title"], "published_at": n.get("date") or n.get("published")})
    return out


# ---------------------------------------------------------------- company: LinkedIn company page + Crunchbase portfolio

LINKEDIN_COMPANY_DATASET = os.getenv("BRIGHTDATA_LINKEDIN_COMPANY_DATASET", "gd_l1vikfnt1wgvvqz95w")
CRUNCHBASE_DATASET = os.getenv("BRIGHTDATA_CRUNCHBASE_DATASET", "gd_l1vijqt9jfj7olije")
PORTFOLIO_POLL_S, PORTFOLIO_MAX_S = 10, 420


def _slugs(name: str, domain: str | None) -> list[str]:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    out = [base, base.replace("-", "")]
    if domain:
        out.append(re.sub(r"^(www\.)?", "", domain.lower()).split(".")[0])
    return list(dict.fromkeys(s for s in out if s))


def _scrape(dataset: str, url: str) -> dict | None:
    r = httpx.post(f"{API}/datasets/v3/scrape?dataset_id={dataset}&format=json", headers=_headers(), timeout=TIMEOUT,
                   json={"input": [{"url": url}]})
    if r.status_code != 200:
        raise RuntimeError(f"dataset {r.status_code}: {r.text[:120]}")
    d = r.json()
    d = d[0] if isinstance(d, list) and d else d
    return d if isinstance(d, dict) and d.get("name") and not d.get("error") else None


def company_profile(company: str, domain: str | None, known_url: str | None = None) -> dict | None:
    """LinkedIn company page via Datasets: what they do + recent updates ('current projects')."""
    urls = [known_url] if known_url else [f"https://www.linkedin.com/company/{s}/" for s in _slugs(company, domain)[:2]]
    for url in urls:
        d = _scrape(LINKEDIN_COMPANY_DATASET, url)
        if not d:
            continue
        if not (set(company.lower().split()) & set(str(d.get("name", "")).lower().split())):
            continue  # guessed slug landed on a different company
        updates = []
        for u in (d.get("updates") or [])[:4]:
            text = (u.get("text") or u.get("title") or "").strip()
            if text:
                updates.append({"url": u.get("post_url") or u.get("url") or d.get("url") or url, "title": text[:240],
                                "published_at": u.get("date") or u.get("time")})
        return {"name": d.get("name"), "about": (d.get("about") or d.get("description") or "")[:600], "website": d.get("website"),
                "industry": d.get("industries"), "size": d.get("company_size"), "linkedin": d.get("url") or url, "updates": updates}
    return None


def _parse_portfolio(d: dict) -> dict:
    items = []
    for inv in (d.get("investments") or [])[:25]:
        org = inv.get("organization") or {}
        rnd = (inv.get("funding_round") or {}).get("value") or ""
        if org.get("value"):
            items.append({"name": org["value"], "round": rnd.split(" - ")[0] or None, "lead": bool(inv.get("lead_investor")),
                          "url": f"https://www.crunchbase.com/organization/{org['id']}" if org.get("id") else None})
    exits = [e.get("value") for e in (d.get("exits") or [])[:6] if e.get("value")]
    return {"items": items, "exits": exits, "num_investments": d.get("num_investments"), "about": d.get("about")}


def start_portfolio_job(company: str, domain: str | None) -> str | None:
    """Crunchbase takes 1-2 min, so trigger it and let a background thread write INVESTED_IN edges when it lands."""
    slug = _slugs(company, domain)[0]
    r = httpx.post(f"{API}/datasets/v3/trigger?dataset_id={CRUNCHBASE_DATASET}&format=json", headers=_headers(), timeout=30,
                   json=[{"url": f"https://www.crunchbase.com/organization/{slug}"}])
    if r.status_code != 200:
        raise RuntimeError(f"Crunchbase trigger {r.status_code}: {r.text[:120]}")
    snapshot = r.json().get("snapshot_id")
    store.set_company_job(company, snapshot, "running")
    threading.Thread(target=_poll_portfolio, args=(company, snapshot), daemon=True).start()
    return snapshot


def _poll_portfolio(company: str, snapshot: str) -> None:
    deadline = time.time() + PORTFOLIO_MAX_S
    while time.time() < deadline:
        time.sleep(PORTFOLIO_POLL_S)
        try:
            st = httpx.get(f"{API}/datasets/v3/progress/{snapshot}", headers=_headers(), timeout=30).json().get("status")
            if st == "failed":
                break
            if st != "ready":
                continue
            data = httpx.get(f"{API}/datasets/v3/snapshot/{snapshot}?format=json", headers=_headers(), timeout=60).json()
            d = data[0] if isinstance(data, list) and data else data
            p = _parse_portfolio(d if isinstance(d, dict) else {})
            store.save_portfolio(company, p["items"])
            store.set_company_job(company, snapshot, f"ready: {len(p['items'])} investments")
            print(f"[intel] Crunchbase portfolio for {company}: {len(p['items'])} investments")
            return
        except Exception as e:
            print(f"[intel] portfolio poll for {company}: {e}")
    store.set_company_job(company, snapshot, "failed")


# ---------------------------------------------------------------- orchestration


def research(person: str) -> dict:
    """Every Bright Data lookup for one person, run in parallel, stored in the graph. Returns what was found + steps."""
    row = run(
        """MATCH (p:Person {name:$p}) OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company)
           RETURN p.linkedin AS linkedin, p.persona AS persona, c.name AS company, c.domain AS domain, c.linkedin AS company_li""",
        {"p": person},
    )
    if not row:
        return {"person": person, "error": f"I haven't met anyone called {person}"}
    r0 = row[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        person_f = pool.submit(_research_person, person, r0["linkedin"], r0["company"])
        company_f = pool.submit(_research_company, r0["company"], r0["domain"], r0["company_li"], r0["persona"], person)
        out, company_out = person_f.result(), company_f.result()
    out["steps"] = out["steps"] + company_out.pop("steps")
    out.update(company_out)
    out["persona"] = r0["persona"]
    return out


class _DocTopics(BaseModel):
    url: str
    topics: list[str]


class _Tagged(BaseModel):
    docs: list[_DocTopics]


TAG_PROMPT = """Tag each page from {company} with 2-4 short lowercase topic phrases ("gpu inference", "seed investing").
Topics from the conversation: {discussed}. Reuse one EXACTLY as written only if the page text clearly supports it;
never add a topic the page doesn't cover.
Return one entry per page, copying the url.

{pages}"""


def write_company_webdocs(company: str, domain: str | None, profile: dict, person: str) -> int:
    """LinkedIn company page + its updates -> WebDocs with topics, so Common Ground fires for live recordings
    (B's SERP-based enrich pipeline can't run without a SERP zone). Returns how many docs were written."""
    from app import llm
    from app.contract import EnrichResult, WebDoc
    from app.graph import writes

    pages = [{"url": profile.get("linkedin") or f"https://www.linkedin.com/company/{_slugs(company, domain)[0]}/",
              "title": f"{company}: {(profile.get('about') or '')[:160]}", "kind": "site", "text": profile.get("about") or ""}]
    pages += [{"url": u["url"], "title": u["title"][:160], "kind": "news", "text": u["title"]}
              for u in profile.get("updates", []) if u.get("url")]
    pages = list({p["url"]: p for p in pages if p["text"]}.values())  # dedupe by URL, drop empty pages
    if not pages:
        return 0
    discussed = [r["t"] for r in run(
        "MATCH (s:Session)-[:WITH]->(:Person {name:$p}) MATCH (s)-[:DISCUSSED]->(t:Topic) RETURN DISTINCT t.name AS t", {"p": person})]
    tagged = llm.parse(TAG_PROMPT.format(company=company, discussed=", ".join(discussed) or "(none)",
                                         pages="\n".join(f"- url: {p['url']}\n  text: {p['text'][:500]}" for p in pages)), _Tagged)
    topics = {d.url: d.topics for d in tagged.docs}
    docs = [WebDoc(url=p["url"], title=p["title"], kind=p["kind"], topics=topics.get(p["url"], [])) for p in pages]
    writes.write_webdocs(EnrichResult(company=company, domain=domain, webdocs=docs, jobs=[]))
    return len(docs)


def _research_company(company: str | None, domain: str | None, known_url: str | None, persona: str | None, person: str) -> dict:
    steps: list[dict] = []
    if not company:
        return {"company_profile": None, "portfolio": [], "portfolio_status": None, "steps": steps}
    profile = None
    is_seed = _is_seed(person)
    if _live("datasets") and not is_seed:
        try:
            profile = company_profile(company, domain, known_url)
            steps.append({"step": f"{company} on LinkedIn · Datasets", "ok": bool(profile),
                          "detail": f"{len(profile['updates'])} recent updates" if profile else "page not found"})
        except Exception as e:
            _mark_down("datasets", str(e))
            steps.append({"step": f"{company} LinkedIn page · Datasets", "ok": False, "detail": str(e)[:160]})
        if persona in ("investor", "accelerator"):
            try:
                start_portfolio_job(company, domain)
                steps.append({"step": f"{company} portfolio · Crunchbase (running in background)", "ok": True, "detail": "1-2 min"})
            except Exception as e:
                steps.append({"step": f"{company} portfolio · Crunchbase", "ok": False, "detail": str(e)[:160]})
    if not profile and is_seed:
        demo = _demo_intel(person) or {}
        if demo.get("company"):
            profile = {**demo["company"], "updates": demo.get("company_updates", [])}
            store.save_portfolio(company, demo.get("portfolio", []))
            if demo.get("portfolio"):
                store.set_company_job(company, None, f"ready: {len(demo['portfolio'])} investments")
            steps.append({"step": f"{company}: demo company profile (seed)", "ok": True, "detail": "seed data"})
    if profile:
        store.save_company(company, profile, profile.get("updates", []))
    if profile and not is_seed:  # seed companies already have tagged WebDocs
        try:
            n = write_company_webdocs(company, domain, profile, person)
            steps.append({"step": f"Tagged {n} {company} pages for Common Ground", "ok": True, "detail": "graph"})
        except Exception as e:
            steps.append({"step": "Common Ground tagging", "ok": False, "detail": str(e)[:160]})
    ci = store.company_intel(company)
    return {"company_profile": {**ci, "updates": (profile or {}).get("updates", [])} if (profile or ci.get("about")) else None,
            "portfolio": ci.get("portfolio", []), "portfolio_status": ci.get("portfolio_status"), "steps": steps}


def _research_person(person: str, linkedin: str | None, company: str | None) -> dict:
    steps, profile, posts, news = [], None, [], []

    if not linkedin and not _is_seed(person) and _live("serp"):
        try:
            linkedin = find_linkedin(person, company)
            steps.append({"step": "Found LinkedIn via Google · SERP", "ok": bool(linkedin), "detail": linkedin})
        except Exception as e:
            _mark_down("serp", str(e))
            steps.append({"step": "LinkedIn search · SERP", "ok": False, "detail": str(e)[:160]})
    if linkedin and "-demo" not in linkedin and not _is_seed(person) and _live("datasets"):  # seed people are fictional
        try:
            profile = linkedin_profile(linkedin)
            posts = profile.pop("posts", [])
            steps.append({"step": "LinkedIn profile + posts · Datasets", "ok": True, "detail": f"{len(posts)} recent posts"})
        except Exception as e:
            _mark_down("datasets", str(e))
            steps.append({"step": "LinkedIn profile · Datasets", "ok": False, "detail": str(e)[:160]})
    if company and not _is_seed(person) and _live("serp"):
        try:
            news = fresh_news(company)
            steps.append({"step": f"{company} news, past 7 days · SERP", "ok": True, "detail": f"{len(news)} articles"})
        except Exception as e:
            _mark_down("serp", str(e))
            steps.append({"step": "Company news · SERP", "ok": False, "detail": str(e)[:160]})

    if not (posts or news):
        demo = _demo_intel(person)
        if demo:
            profile, posts, news = demo.get("profile"), demo.get("posts", []), demo.get("news", [])
            steps.append({"step": "Demo profile (seed person)", "ok": True, "detail": "seed data"})

    store.save_intel(person, company, profile, posts, news)
    return {"person": person, "company": company, "linkedin": linkedin or (profile or {}).get("url"),
            "headline": (profile or {}).get("headline"), "posts": posts, "news": news, "steps": steps}


def _is_seed(person: str) -> bool:
    """Fictional seed people: never scrape the live web for them (their companies don't exist)."""
    path = settings.SEED_DIR / "intel" / "personas.json"
    return _demo_intel(person) is not None or (path.exists() and person in json.loads(path.read_text()))


def _demo_intel(person: str) -> dict | None:
    path = settings.SEED_DIR / "intel" / (re.sub(r"[^a-z0-9]+", "_", person.lower()).strip("_") + ".json")
    return json.loads(path.read_text()) if path.exists() else None

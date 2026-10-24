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
import time
from urllib.parse import quote_plus

import httpx

from app.config import settings
from app.agent import store
from app.graph.db import run

API = "https://api.brightdata.com"
LINKEDIN_DATASET = os.getenv("BRIGHTDATA_LINKEDIN_DATASET", "gd_l1viktl72bvl7bjuj0")  # LinkedIn people profiles
TIMEOUT = 45.0
_down_until = 0.0
_last_error = ""


def status() -> dict:
    return {"available": time.time() >= _down_until, "last_error": _last_error}


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.BRIGHTDATA_API_KEY}", "Content-Type": "application/json"}


def _mark_down(err: str) -> None:
    global _down_until, _last_error
    _down_until, _last_error = time.time() + 300, err[:200]
    print(f"[intel] Bright Data unavailable for 5 min: {_last_error}")


def _live() -> bool:
    return not settings.MOCK_MODE and bool(settings.BRIGHTDATA_API_KEY) and time.time() >= _down_until


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
    if not isinstance(d, dict):
        return {"url": url, "headline": None, "posts": []}
    raw_posts = d.get("posts") or d.get("activity") or []
    posts = []
    for p in raw_posts[:5]:
        text = p.get("title") or p.get("text") or p.get("attribution") or ""
        link = p.get("link") or p.get("url")
        if text and link:
            posts.append({"url": link, "text": text[:280], "posted_at": p.get("created_at") or p.get("date"), "source": "linkedin"})
    company = d.get("current_company") if isinstance(d.get("current_company"), dict) else {}
    return {
        "url": url,
        "headline": d.get("position") or d.get("headline") or company.get("title"),
        "posts": posts,
    }


def fresh_news(company: str) -> list[dict]:
    data = _serp(f'"{company}"', "&tbm=nws&tbs=qdr:w")
    items = data.get("news") or data.get("organic") or []
    out = []
    for n in items[:4]:
        if n.get("link") and n.get("title"):
            out.append({"url": n["link"], "title": n["title"], "published_at": n.get("date") or n.get("published")})
    return out


# ---------------------------------------------------------------- orchestration


def research(person: str) -> dict:
    """Run every Bright Data lookup for one person, store results, return what we found + which steps ran live."""
    row = run(
        "MATCH (p:Person {name:$p}) OPTIONAL MATCH (p)-[:WORKS_AT]->(c:Company) RETURN p.linkedin AS linkedin, c.name AS company",
        {"p": person},
    )
    if not row:
        return {"person": person, "error": f"I haven't met anyone called {person}"}
    linkedin, company = row[0]["linkedin"], row[0]["company"]
    steps, profile, posts, news = [], None, [], []

    if _live():
        try:
            if not linkedin:
                linkedin = find_linkedin(person, company)
                steps.append({"step": "Found LinkedIn via Google (Bright Data SERP)", "ok": bool(linkedin), "detail": linkedin})
            if linkedin:
                profile = linkedin_profile(linkedin)
                posts = profile.pop("posts", [])
                steps.append({"step": "Scraped LinkedIn profile + posts (Bright Data Datasets)", "ok": True, "detail": f"{len(posts)} recent posts"})
            if company:
                news = fresh_news(company)
                steps.append({"step": f"This week's news on {company} (Bright Data SERP)", "ok": True, "detail": f"{len(news)} articles"})
        except Exception as e:
            _mark_down(str(e))
            steps.append({"step": "Bright Data", "ok": False, "detail": _last_error})

    if not (profile or posts or news):
        demo = _demo_intel(person)
        if demo:
            profile, posts, news = demo.get("profile"), demo.get("posts", []), demo.get("news", [])
            steps.append({"step": "Bright Data offline: using cached demo intel", "ok": True, "detail": "seed data"})

    store.save_intel(person, company, profile, posts, news)
    return {"person": person, "company": company, "linkedin": linkedin or (profile or {}).get("url"),
            "headline": (profile or {}).get("headline"), "posts": posts, "news": news, "steps": steps}


def _demo_intel(person: str) -> dict | None:
    path = settings.SEED_DIR / "intel" / (re.sub(r"[^a-z0-9]+", "_", person.lower()).strip("_") + ".json")
    return json.loads(path.read_text()) if path.exists() else None

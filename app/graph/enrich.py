"""Bright Data enrichment pipeline: serp() -> fetch() -> parse_page() -> write_webdocs().
Mock mode serves cached results from seed/webdocs/*.json instead of hitting the network."""
import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel

from app import llm
from app.config import settings
from app.contract import EnrichResult, Job, WebDoc
from app.graph import brightdata, writes

MAX_PAGES = 10
MAX_CHARS = 12_000

SEARCHES = [
    '"{name}" official site',
    '"{name}" engineering blog',
    '"{name}" careers jobs',
    '"{name}" news funding',
    'site:github.com "{name}"',
]


class PageParse(BaseModel):
    """LLM output for one page. No defaults — strict schema."""
    title: str
    kind: str  # blog | news | repo | job | site
    published_at: str | None
    topics: list[str]
    job_titles: list[str]
    job_skills: list[str]
    sector: str | None
    stage: str | None


def _cache_path(url: str) -> Path:
    return settings.CACHE_DIR / "pages" / (hashlib.sha1(url.encode()).hexdigest() + ".html")


def fetch(url: str) -> str:
    """Fetch through Bright Data, cached on disk by URL hash."""
    p = _cache_path(url)
    if p.exists():
        return p.read_text(errors="ignore")
    html = brightdata.fetch(url)
    p.write_text(html)
    return html


def _text(html: str) -> str:
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()[:MAX_CHARS]


def parse_page(url: str, html: str, company: str) -> PageParse:
    prompt = (
        f"Company: {company}\nURL: {url}\n\n"
        "Classify this page as one of: blog, news, repo, job, site. Extract the title, an ISO publish date if visible "
        "(else null), 3-6 short lowercase topic tags (e.g. 'gpu inference', 'cold starts'), any job titles listed on the "
        "page and the skills those jobs require, plus your best guess at the company's sector and funding stage "
        "(e.g. 'Series B') if the page says so, else null.\n\nPAGE TEXT:\n" + _text(html)
    )
    return llm.parse(prompt, PageParse)


def enrich_company(name: str, domain: str | None = None, write: bool = True) -> EnrichResult:
    result = _mock(name, domain) if settings.MOCK_MODE else _live(name, domain)
    if write:
        writes.write_webdocs(result)
    return result


def _live(name: str, domain: str | None) -> EnrichResult:
    urls: list[str] = []
    for tmpl in SEARCHES:
        try:
            for hit in brightdata.serp(tmpl.format(name=name), limit=3):
                if hit["url"] not in urls:
                    urls.append(hit["url"])
        except Exception as e:  # keep going; one failed search shouldn't kill enrichment
            print(f"[enrich] serp failed for {tmpl!r}: {e}")
    urls = urls[:MAX_PAGES]
    if not domain:
        for u in urls:
            if "github.com" not in u and "linkedin.com" not in u:
                domain = re.sub(r"^https?://(www\.)?", "", u).split("/")[0]
                break

    webdocs, jobs, sectors, stages = [], [], [], []
    for url in urls:
        try:
            parsed = parse_page(url, fetch(url), name)
        except Exception as e:
            print(f"[enrich] skip {url}: {e}")
            continue
        kind = parsed.kind if parsed.kind in ("blog", "news", "repo", "job", "site") else "site"
        webdocs.append(WebDoc(url=url, title=parsed.title, kind=kind, published_at=parsed.published_at, topics=parsed.topics))
        for jt in parsed.job_titles:
            jobs.append(Job(title=jt, url=url, skills=parsed.job_skills))
        if parsed.sector:
            sectors.append(parsed.sector)
        if parsed.stage:
            stages.append(parsed.stage)
    pick = lambda xs: max(set(xs), key=xs.count) if xs else None  # noqa: E731
    return EnrichResult(company=name, domain=domain, sector=pick(sectors), stage=pick(stages), webdocs=webdocs, jobs=jobs)


def _mock(name: str, domain: str | None) -> EnrichResult:
    """Look up a cached fixture by company name or domain. Unknown companies get an empty result."""
    wanted_name = name.strip().lower()
    wanted_domain = (domain or "").strip().lower()
    for path in sorted((settings.SEED_DIR / "webdocs").glob("*.json")):
        data = json.loads(path.read_text())
        if data.get("company", "").lower() == wanted_name or (wanted_domain and data.get("domain", "").lower() == wanted_domain):
            return EnrichResult(**data)
    return EnrichResult(company=name, domain=domain)

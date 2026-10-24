"""The ONLY module that talks to Bright Data.

TODO(verify): confirm the request shape against https://docs.brightdata.com — this uses the
"Web Unlocker / SERP API direct request" endpoint:
    POST https://api.brightdata.com/request
    Authorization: Bearer $BRIGHTDATA_API_KEY
    {"zone": "<zone>", "url": "<url>", "format": "raw"}
For SERP we request a Google search URL through BRIGHTDATA_SERP_ZONE and append `brd_json=1`
so Bright Data returns parsed JSON instead of HTML (fall back to regex on HTML if not).
"""
import json
import re
from urllib.parse import quote_plus

import httpx

from app.config import settings

ENDPOINT = "https://api.brightdata.com/request"
TIMEOUT = 60.0


def _request(zone: str | None, url: str) -> str:
    if not settings.BRIGHTDATA_API_KEY or not zone:
        raise RuntimeError("BRIGHTDATA_API_KEY / zone not configured (or set MOCK_MODE=true)")
    headers = {"Authorization": f"Bearer {settings.BRIGHTDATA_API_KEY}", "Content-Type": "application/json"}
    body = {"zone": zone, "url": url, "format": "raw"}
    with httpx.Client(timeout=TIMEOUT) as client:
        res = client.post(ENDPOINT, headers=headers, json=body)
        res.raise_for_status()
        return res.text


def serp(query: str, limit: int = 5) -> list[dict]:
    """Google search via the SERP zone. Returns [{"url", "title", "snippet"}]."""
    url = f"https://www.google.com/search?q={quote_plus(query)}&num={limit}&brd_json=1"
    raw = _request(settings.BRIGHTDATA_SERP_ZONE, url)
    results: list[dict] = []
    try:
        data = json.loads(raw)
        for item in data.get("organic", [])[:limit]:
            results.append({"url": item.get("link"), "title": item.get("title"), "snippet": item.get("description")})
    except json.JSONDecodeError:
        # Fallback: scrape hrefs out of raw HTML. Crude on purpose.
        for m in re.finditer(r'<a href="(https?://(?!www\.google\.)[^"]+)"', raw):
            results.append({"url": m.group(1), "title": None, "snippet": None})
            if len(results) >= limit:
                break
    return [r for r in results if r.get("url")]


def fetch(url: str) -> str:
    """Fetch a page through the Unlocker zone. Returns raw HTML."""
    return _request(settings.BRIGHTDATA_UNLOCKER_ZONE, url)

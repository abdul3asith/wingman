"""Save debriefs you recorded through the app as seed fixtures (seed/sessions/*.json). OWNER: Person A.

Usage (API must be running):
    python scripts/export_seed.py                 # list sessions in the graph (no files written)
    python scripts/export_seed.py s_ab12cd34 ...  # export specific session ids  <- recommended
    python scripts/export_seed.py --all-live      # export every live-recorded session not already in seed/
                                                  # (skips smoke-test sessions)
    add --out DIR to write somewhere other than seed/sessions/

Then `make seed` (or `make reset-graph`) reproduces them, and Person B saves their companies' enrichment
into seed/webdocs/ so MOCK_MODE replays the whole demo offline.
"""
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "seed" / "sessions"
BASE = "http://localhost:8000"
LIVE_ID = re.compile(r"^s_[0-9a-f]{8}$")  # ids minted by POST /sessions and /sessions/debrief-text


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def existing_ids() -> set[str]:
    return {json.loads(p.read_text())["session_id"] for p in SEED.glob("*.json")}


def to_extract(d: dict) -> dict:
    """GET /sessions/{id} detail -> SessionExtract JSON (app/contract.py)."""
    return {
        "session_id": d["session_id"],
        "started_at": d["started_at"],
        "transcript": d.get("transcript") or "",
        "summary": d.get("summary") or "",
        "person": {"name": d["person"], "role": d.get("role"), "role_class": d.get("role_class") or "other", "email": d.get("email")},
        "company": {"name": d["company"], "domain": d.get("domain")} if d.get("company") else None,
        "topics": d.get("topics") or [],
        "promises": [{"by": p["by"], "text": p["text"]} for p in d.get("promises") or []],
    }


def main(args: list[str]) -> None:
    out_dir = SEED
    if "--out" in args:
        i = args.index("--out")
        out_dir = Path(args[i + 1]).resolve()
        args = args[:i] + args[i + 2:]
    out_dir.mkdir(parents=True, exist_ok=True)

    c = httpx.Client(base_url=BASE, timeout=30)
    sessions = c.get("/sessions").raise_for_status().json()
    ids = [a for a in args if not a.startswith("--")]
    if not ids and "--all-live" not in args:
        for s in sessions:
            print(f"{s['session_id']:22} {s['person']:22} {s.get('company') or '-':22} {s['started_at']}  {(s.get('summary') or '')[:50]}")
        print("\nexport with: python scripts/export_seed.py <session_id> [<session_id> ...]")
        return

    have = existing_ids()
    if not ids:  # --all-live
        for s in sessions:
            if not LIVE_ID.match(s["session_id"]) or s["session_id"] in have:
                continue
            d = c.get(f"/sessions/{s['session_id']}").raise_for_status().json()
            if "smoke" in (d.get("transcript") or "").lower():
                continue
            ids.append(s["session_id"])

    n = len(list(out_dir.glob("*.json")))
    for sid in ids:
        if sid in have and out_dir == SEED:
            print(f"skip {sid}: already in seed/sessions")
            continue
        x = to_extract(c.get(f"/sessions/{sid}").raise_for_status().json())
        n += 1
        path = out_dir / f"{n:02d}_{slug(x['company']['name'] if x['company'] else 'nocompany')}_{slug(x['person']['name'].split()[0])}.json"
        path.write_text(json.dumps(x, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {path}  ({x['person']['name']} @ {x['company']['name'] if x['company'] else '-'})")
    if not ids:
        print("nothing new to export")


if __name__ == "__main__":
    main(sys.argv[1:])

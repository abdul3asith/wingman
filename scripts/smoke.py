"""Hit every endpoint in order. Usage: python scripts/smoke.py [base_url]  (default http://localhost:8000)"""
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
c = httpx.Client(base_url=BASE, timeout=120)
failures = 0


def check(name, fn):
    global failures
    try:
        out = fn()
        print(f"PASS  {name}" + (f"  → {out}" if out is not None else ""))
        return out
    except Exception as e:
        failures += 1
        print(f"FAIL  {name}  → {e}")
        return None


def ok(res, want=200):
    if res.status_code != want:
        raise AssertionError(f"{res.status_code} {res.text[:200]}")
    return res.json()


health = check("GET /health", lambda: ok(c.get("/health")))
if health and health.get("graph_status") != "ok":
    print("FalkorDB unreachable — run `make up` first."); sys.exit(1)

check("GET / (web UI)", lambda: "html" if "<html" in c.get("/").text.lower() else (_ for _ in ()).throw(AssertionError("no html")))

sid = check("POST /sessions (transcript)", lambda: ok(c.post("/sessions", data={"transcript": "smoke test transcript"}))["session_id"])
extract = check("POST /sessions/{id}/process", lambda: ok(c.post(f"/sessions/{sid}/process", params={"sync_enrich": True})))
person = extract["person"]["name"] if extract else None
check("POST /sessions/debrief-text", lambda: ok(c.post("/sessions/debrief-text", json={"text": "typed smoke debrief"}))["person"]["name"])
check("GET /sessions", lambda: f"{len(ok(c.get('/sessions')))} sessions")
check("GET /sessions/{id}", lambda: ok(c.get(f"/sessions/{sid}"))["person"])

check("POST /graph/enrich", lambda: f"{len(ok(c.post('/graph/enrich', json={'company': 'Lattice Compute', 'domain': 'latticecompute.ai'}))['webdocs'])} webdocs")
cg = check("GET /graph/common-ground", lambda: ok(c.get("/graph/common-ground")))
if cg is not None and len(cg) == 0:
    failures += 1; print("FAIL  common ground is empty — seed not loaded? run `make seed`")
check("GET /graph/common-ground?person=", lambda: f"{len(ok(c.get('/graph/common-ground', params={'person': person})))} rows for {person}")
check("GET /graph/referral-radar", lambda: f"{len(ok(c.get('/graph/referral-radar')))} rows")
check("GET /graph/segment?sector=AI infrastructure", lambda: f"{len(ok(c.get('/graph/segment', params={'sector': 'AI infrastructure'})))} people")
check("GET /graph/promises", lambda: f"{len(ok(c.get('/graph/promises')))} open")
check("GET /graph/people", lambda: f"{len(ok(c.get('/graph/people')))} people")
presets = check("GET /graph/presets", lambda: [p["name"] for p in ok(c.get("/graph/presets"))])
for name in presets or []:
    check(f"POST /graph/query/{name}", lambda name=name: f"{len(ok(c.post(f'/graph/query/{name}')))} rows")
check("GET /graph/stats", lambda: ok(c.get("/graph/stats")))

drafts = check("POST /asks/generate", lambda: ok(c.post("/asks/generate", json={})))
check("POST /asks/generate (one person)", lambda: ok(c.post("/asks/generate", json={"person": person}))[0]["ask_type"])
queue = check("GET /asks/queue", lambda: ok(c.get("/asks/queue")))
did = next((d["id"] for d in (queue or []) if d["person"] == person), (queue or [{}])[0].get("id") if queue else None)
check("GET /graph/why/{draft_id}", lambda: f"{len(ok(c.get(f'/graph/why/{did}'))['nodes'])} nodes")
# dry_run: smoke must never send a real email, even with RESEND_API_KEY set.
check("POST /asks/{id}/approve?dry_run", lambda: ok(c.post(f"/asks/{did}/approve", params={"dry_run": True}))["status"])
skip_id = next((d["id"] for d in (queue or []) if d["id"] != did), None)
if skip_id:
    check("POST /asks/{id}/skip", lambda: ok(c.post(f"/asks/{skip_id}/skip"))["status"])
check("GET /asks/queue?status=all", lambda: f"{len(ok(c.get('/asks/queue', params={'status': 'all'})))} drafts total")

print(f"\n{'ALL PASS' if failures == 0 else f'{failures} FAILED'}")
sys.exit(1 if failures else 0)

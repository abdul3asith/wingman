"""/graph/* — OWNER: Person B."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.contract import CommonGround, EnrichResult
from app.graph import db, enrich, queries, schema, writes

router = APIRouter(prefix="/graph", tags=["graph"])


class EnrichRequest(BaseModel):
    company: str
    domain: str | None = None


@router.get("/common-ground", response_model=list[CommonGround])
def common_ground(person: str | None = None):
    return queries.common_ground(settings.USER_ID, person)


@router.get("/referral-radar")
def referral_radar():
    return queries.referral_radar(settings.USER_ID)


@router.get("/segment")
def segment(sector: str | None = None, stage: str | None = None, role_class: str | None = None):
    return queries.segment(settings.USER_ID, sector, stage, role_class)


@router.get("/why/{draft_id}")
def why(draft_id: str):
    out = queries.why_path(draft_id)
    if not out:
        raise HTTPException(404, f"draft {draft_id} not found")
    return out


@router.get("/promises")
def promises():
    return queries.open_promises(settings.USER_ID)


@router.get("/people")
def people():
    return queries.people(settings.USER_ID)


@router.post("/enrich", response_model=EnrichResult)
def enrich_company(req: EnrichRequest):
    return enrich.enrich_company(req.company, req.domain)


@router.get("/presets")
def presets():
    return [{"name": k, "description": v["description"], "cypher": " ".join(v["cypher"].split())} for k, v in queries.PRESETS.items()]


@router.post("/query/{name}")
def run_preset(name: str):
    if name not in queries.PRESETS:
        raise HTTPException(404, f"unknown preset {name}; see GET /graph/presets")
    return queries.run_preset(name, settings.USER_ID)


@router.get("/stats")
def stats():
    return queries.stats()


@router.post("/reset")
def reset(reseed: bool = True):
    db.reset()
    created = schema.ensure()
    writes.ensure_user()
    loaded = None
    if reseed:
        from seed.load_seed import load_all

        loaded = load_all()
    return {"reset": True, "schema": created, "seeded": loaded}

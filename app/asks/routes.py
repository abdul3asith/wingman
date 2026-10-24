"""POST /asks/generate, GET /asks/queue, POST /asks/{id}/approve — OWNER: Person A."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.asks import drafts, send
from app.contract import Draft
from app.graph import queries, writes

router = APIRouter(prefix="/asks", tags=["asks"])


class GenerateRequest(BaseModel):
    person: str | None = None  # None = every person you've met


@router.post("/generate", response_model=list[Draft])
def generate(req: GenerateRequest | None = None):
    return drafts.generate((req or GenerateRequest()).person)


@router.get("/queue", response_model=list[Draft])
def queue(status: str | None = "pending"):
    return queries.draft_queue(None if status in (None, "", "all") else status)


@router.post("/{draft_id}/approve", response_model=Draft)
def approve(draft_id: str):
    d = queries.get_draft(draft_id)
    if d is None:
        raise HTTPException(404, f"draft {draft_id} not found")
    if d.status == "sent":
        return d
    try:
        send.send(d)
    except ValueError as e:
        raise HTTPException(400, str(e))
    writes.set_draft_status(draft_id, "sent")
    d.status = "sent"
    return d


@router.post("/{draft_id}/skip", response_model=Draft)
def skip(draft_id: str):
    d = queries.get_draft(draft_id)
    if d is None:
        raise HTTPException(404, f"draft {draft_id} not found")
    writes.set_draft_status(draft_id, "skipped")
    d.status = "skipped"
    return d

"""POST /asks/generate, GET /asks/queue, POST /asks/{id}/approve — OWNER: Person A."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.asks import drafts, send
from app.contract import Draft
from app.ingest import graph_bridge as graph

router = APIRouter(prefix="/asks", tags=["asks"])


class GenerateRequest(BaseModel):
    person: str | None = None  # None = every person you've met


class ApproveRequest(BaseModel):
    """Optional edits made in the queue before approving. Omitted fields keep the drafted value."""
    subject: str | None = None
    body: str | None = None
    email: str | None = None


@router.post("/generate", response_model=list[Draft])
def generate(req: GenerateRequest | None = None):
    return drafts.generate((req or GenerateRequest()).person)


@router.get("/queue", response_model=list[Draft])
def queue(status: str | None = "pending"):
    return graph.draft_queue(None if status in (None, "", "all") else status)


@router.post("/{draft_id}/approve", response_model=Draft)
def approve(draft_id: str, edits: ApproveRequest | None = None, dry_run: bool = False):
    """The only way an email goes out: a human clicks Approve. dry_run=true (smoke tests) sends nothing, changes nothing."""
    d = graph.get_draft(draft_id)
    if d is None:
        raise HTTPException(404, f"draft {draft_id} not found")
    if d.status == "sent" or dry_run:
        return d
    if edits:
        changes = {k: v for k, v in edits.model_dump().items() if v is not None}
        if changes:
            d = d.model_copy(update=changes)
            graph.write_draft(d)
    try:
        send.send(d)
    except ValueError as e:
        raise HTTPException(400, str(e))
    graph.set_draft_status(draft_id, "sent")
    d.status = "sent"
    return d


@router.post("/{draft_id}/skip", response_model=Draft)
def skip(draft_id: str):
    d = graph.get_draft(draft_id)
    if d is None:
        raise HTTPException(404, f"draft {draft_id} not found")
    graph.set_draft_status(draft_id, "skipped")
    d.status = "skipped"
    return d

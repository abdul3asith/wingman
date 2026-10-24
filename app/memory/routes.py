"""GET /memory/goal: who you met that advances your goal, and what they told you."""
from fastapi import APIRouter

from app.config import settings
from app.graph import queries

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/goal")
def goal():
    return {"goal": settings.USER_GOAL, "connections": queries.goal_map(settings.USER_ID)}

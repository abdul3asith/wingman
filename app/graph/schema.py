"""Indexes. Idempotent: every statement is wrapped so reruns are no-ops."""
from app.config import settings
from app.graph.db import run

RANGE_INDEXES = [
    ("Person", "name"),
    ("Company", "name"),
    ("Topic", "name"),
    ("WebDoc", "url"),
    ("Session", "id"),
    ("Draft", "id"),
    ("Job", "url"),
    ("Skill", "name"),
    ("User", "id"),
    ("Recording", "id"),
    ("Fact", "id"),
]

# TODO(workshop): confirm vector index + vecf32() syntax against the FalkorDB version on the demo box.
# Topic: topic dedup in writes.merge_topic. Fact / Session: event-memory similarity search (app.graph.memory).
VECTOR_INDEXES = [("Topic", "embedding"), ("Fact", "embedding"), ("Session", "embedding")]


def _vector_index(label: str, prop: str) -> str:
    return (
        f"CREATE VECTOR INDEX FOR (n:{label}) ON (n.{prop}) "
        f"OPTIONS {{dimension:{settings.EMBED_DIM}, similarityFunction:'cosine'}}"
    )


def ensure() -> dict:
    created, skipped = [], []
    for label, prop in RANGE_INDEXES:
        try:
            run(f"CREATE INDEX FOR (n:{label}) ON (n.{prop})")
            created.append(f"{label}.{prop}")
        except Exception:  # already exists
            skipped.append(f"{label}.{prop}")
    for label, prop in VECTOR_INDEXES:
        try:
            run(_vector_index(label, prop))
            created.append(f"{label}.{prop}(vector)")
        except Exception:  # already exists
            skipped.append(f"{label}.{prop}(vector)")
    return {"created": created, "skipped": skipped}

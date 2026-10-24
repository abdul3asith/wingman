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
]

# TODO(workshop): confirm vector index + vecf32() syntax against the FalkorDB version on the demo box.
VECTOR_INDEX = (
    "CREATE VECTOR INDEX FOR (t:Topic) ON (t.embedding) "
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
    try:
        run(VECTOR_INDEX)
        created.append("Topic.embedding(vector)")
    except Exception:
        skipped.append("Topic.embedding(vector)")
    return {"created": created, "skipped": skipped}

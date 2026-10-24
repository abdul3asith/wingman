"""FalkorDB connection. Always use run(query, params) — never string-format values into Cypher."""
from typing import Any

from app.config import settings

_db = None
_graph = None


class GraphUnavailable(RuntimeError):
    """Raised when FalkorDB is not reachable. main.py turns this into a 503."""


def get_graph():
    global _db, _graph
    if _graph is None:
        from falkordb import FalkorDB

        _db = FalkorDB(host=settings.FALKORDB_HOST, port=settings.FALKORDB_PORT)
        _graph = _db.select_graph(settings.GRAPH_NAME)
    return _graph


def _plain(val: Any) -> Any:
    """Convert falkordb Node/Edge/Path objects into plain dicts so routes can return them as JSON."""
    props = getattr(val, "properties", None)
    if props is not None:
        out = dict(props)
        labels = getattr(val, "labels", None)
        if labels:
            out["_labels"] = list(labels)
        rel = getattr(val, "relation", None)
        if rel:
            out["_type"] = rel
        return out
    if isinstance(val, list):
        return [_plain(v) for v in val]
    if isinstance(val, dict):
        return {k: _plain(v) for k, v in val.items()}
    return val


def run(query: str, params: dict | None = None) -> list[dict]:
    """Run Cypher, return rows as list of dicts keyed by RETURN column names."""
    import redis

    try:
        res = get_graph().query(query, params or {})
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError, ConnectionRefusedError) as e:
        raise GraphUnavailable(f"FalkorDB not reachable at {settings.FALKORDB_HOST}:{settings.FALKORDB_PORT} — run `make up`") from e
    cols = [h[1] for h in res.header] if res.header else []
    return [{col: _plain(v) for col, v in zip(cols, row)} for row in res.result_set]


def scalar(query: str, params: dict | None = None, default: Any = None) -> Any:
    rows = run(query, params)
    if not rows:
        return default
    return next(iter(rows[0].values()))


def reset() -> None:
    """Drop the whole graph (data + indexes)."""
    global _graph
    try:
        get_graph().delete()
    except Exception as e:  # graph may not exist yet
        if "Invalid graph operation on empty key" not in str(e) and "not found" not in str(e).lower():
            raise
    _graph = None

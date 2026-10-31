"""FalkorDB connection. Always use run(query, params) — never string-format values into Cypher."""
import threading
import time
from collections import deque
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


_recent: deque = deque(maxlen=8)  # last queries, printed if FalkorDB dies (find the query that crashed it)
RETRY_WAIT_S = 15  # docker restarts FalkorDB after a crash (restart: unless-stopped); wait this long for it


def _reset() -> None:
    global _db, _graph
    _db = _graph = None


def run(query: str, params: dict | None = None) -> list[dict]:
    """Run Cypher, return rows as list of dicts keyed by RETURN column names. If FalkorDB drops (it can panic
    and auto-restart), wait for it and retry once instead of failing the request."""
    import redis

    _recent.append(f"{time.strftime('%H:%M:%S')} [{threading.current_thread().name}] {' '.join(query.split())[:160]}")
    for attempt in (1, 2):
        try:
            res = get_graph().query(query, params or {})
            break
        except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError, ConnectionRefusedError) as e:
            if attempt == 1:
                print("[db] FalkorDB connection lost; recent queries:\n  " + "\n  ".join(_recent))
                _reset()
                deadline = time.time() + RETRY_WAIT_S
                while time.time() < deadline:
                    time.sleep(1)
                    try:
                        get_graph().query("RETURN 1")
                        break
                    except Exception:
                        _reset()
                continue
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

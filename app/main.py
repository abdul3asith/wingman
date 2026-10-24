"""wingman API. `make run` starts FalkorDB + this app; the web UI is served at /."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent.routes import router as agent_router
from app.asks.routes import router as asks_router
from app.config import settings
from app.graph import queries, schema, writes
from app.graph.db import GraphUnavailable, scalar
from app.graph.routes import router as graph_router
from app.ingest.routes import router as ingest_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        print("[startup] schema:", schema.ensure())
        writes.ensure_user()
        if settings.MOCK_MODE and scalar("MATCH (s:Session) RETURN count(s)", default=0) == 0:
            from seed.load_seed import load_all

            print("[startup] empty graph in MOCK_MODE → loading seed:", load_all())
    except GraphUnavailable as e:
        print(f"[startup] WARNING: {e}")
    yield


app = FastAPI(title="wingman", version="0.1.0", lifespan=lifespan)
app.include_router(ingest_router)
app.include_router(asks_router)
app.include_router(graph_router)
app.include_router(agent_router)


@app.exception_handler(GraphUnavailable)
async def graph_unavailable(_: Request, exc: GraphUnavailable):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health")
def health():
    out = {"ok": True, "mock_mode": settings.MOCK_MODE, "user": settings.USER_NAME, "graph": settings.GRAPH_NAME,
           "falkordb_ui": f"http://localhost:{settings.FALKORDB_UI_PORT}"}
    try:
        out["counts"] = queries.stats()
        out["graph_status"] = "ok"
    except GraphUnavailable as e:
        out["graph_status"] = "unreachable"
        out["graph_error"] = str(e)
    return out


app.mount("/", StaticFiles(directory=str(settings.WEB_DIR), html=True), name="web")

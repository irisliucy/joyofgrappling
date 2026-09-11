import json

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config, export_static, loop, store
from .schemas import ReapConfig

app = FastAPI(title="Joy of Grappling — Reap")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store.init_db()


@app.post("/api/research")
def start_research(cfg: ReapConfig, background_tasks: BackgroundTasks):
    query_id = store.create_query(cfg.query, cfg.model_dump())
    background_tasks.add_task(loop.run, query_id, cfg)
    return {"query_id": query_id}


@app.get("/api/jobs/{query_id}")
def get_job(query_id: str):
    query = store.get_query(query_id)
    if query is None:
        raise HTTPException(404, "unknown query_id")
    return {
        "id": query["id"],
        "query_text": query["query_text"],
        "status": query["status"],
        "progress": query["progress"],
        "has_output": query["output_json"] is not None,
    }


@app.get("/api/output/{query_id}")
def get_output(query_id: str):
    query = store.get_query(query_id)
    if query is None:
        raise HTTPException(404, "unknown query_id")
    if not query["output_json"]:
        raise HTTPException(409, "output not ready yet")
    return json.loads(query["output_json"])


@app.post("/api/export/{query_id}")
def export_query(query_id: str):
    path = export_static.export_query(query_id)
    return {"exported_to": str(path)}


# Serves frontend/ at the site root, same-origin with the /api routes above
# (mounted last so it doesn't shadow them).
app.mount("/", StaticFiles(directory=str(config.ROOT_DIR / "frontend"), html=True), name="frontend")

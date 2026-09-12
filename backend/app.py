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


@app.get("/api/debug/caption/{video_id}")
def debug_caption(video_id: str):
    # Temporary: surfaces the real exception from a caption fetch attempt,
    # since transcript.fetch_captions() normally swallows all errors.
    # Also reports whether a proxy is configured, without leaking secrets.
    from . import config, transcript

    proxy_configured = bool(
        (config.WEBSHARE_PROXY_USERNAME and config.WEBSHARE_PROXY_PASSWORD)
        or config.PROXY_HTTP_URL
        or config.PROXY_HTTPS_URL
    )
    try:
        fetched = transcript._build_api().fetch(video_id)
        return {"proxy_configured": proxy_configured, "success": True, "segment_count": len(fetched.segments)}
    except Exception as e:
        return {"proxy_configured": proxy_configured, "success": False, "error_type": type(e).__name__, "error": str(e)}


@app.get("/api/debug/logs/{query_id}")
def get_debug_logs(query_id: str):
    # Temporary: lets us inspect run_logs on a deployed instance without
    # direct DB/SSH access. Remove once no longer needed.
    with store.get_conn() as conn:
        rows = conn.execute(
            "SELECT iteration, step, status, details_json, created_at FROM run_logs WHERE query_id = ? ORDER BY rowid",
            (query_id,),
        ).fetchall()
        videos = conn.execute("SELECT * FROM videos WHERE query_id = ?", (query_id,)).fetchall()
    return {
        "logs": [dict(r) for r in rows],
        "videos": [dict(v) for v in videos],
    }


# Serves frontend/ at the site root, same-origin with the /api routes above
# (mounted last so it doesn't shadow them).
app.mount("/", StaticFiles(directory=str(config.ROOT_DIR / "frontend"), html=True), name="frontend")

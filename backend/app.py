import json
from datetime import datetime

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, export_static, loop, store
from .schemas import ReapConfig


class FeedbackRequest(BaseModel):
    action: str  # "up" | "down"

app = FastAPI(title="Joy of Grappling")

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

    last_activity = store.get_last_activity(query_id)
    seconds_since_activity = None
    if last_activity:
        last_activity_dt = datetime.strptime(last_activity, "%Y-%m-%d %H:%M:%S")
        seconds_since_activity = (datetime.utcnow() - last_activity_dt).total_seconds()

    return {
        "id": query["id"],
        "query_text": query["query_text"],
        "status": query["status"],
        "progress": query["progress"],
        "has_output": store.has_any_edges(query_id),  # true as soon as anything exists, not just at completion
        "seconds_since_activity": seconds_since_activity,
    }


@app.get("/api/output/{query_id}")
def get_output(query_id: str):
    # Always built live from whatever edges exist right now -- this is what
    # lets the frontend show a partial graph seconds into a run instead of
    # waiting for the whole thing (which can take 30-90+ minutes) to finish.
    query = store.get_query(query_id)
    if query is None:
        raise HTTPException(404, "unknown query_id")
    output = loop.build_output(query_id, query["query_text"])
    return json.loads(output.model_dump_json(by_alias=True))


@app.post("/api/feedback/{query_id}/{edge_id}")
def submit_feedback(query_id: str, edge_id: str, body: FeedbackRequest):
    if body.action not in ("up", "down"):
        raise HTTPException(400, "action must be 'up' or 'down'")
    if store.get_query(query_id) is None:
        raise HTTPException(404, "unknown query_id")
    store.record_feedback(query_id, edge_id, body.action)
    return {"ok": True}


@app.delete("/api/edges/{query_id}/{edge_id}")
def delete_edge(query_id: str, edge_id: str):
    if store.get_query(query_id) is None:
        raise HTTPException(404, "unknown query_id")
    deleted = store.delete_edge(query_id, edge_id)
    if not deleted:
        raise HTTPException(404, "unknown edge_id for this query")
    return {
        "ok": True,
        "has_output": store.has_any_edges(query_id),
    }


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
        return {"proxy_configured": proxy_configured, "success": True, "segment_count": len(list(fetched))}
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


_ERROR_PAGE = (config.ROOT_DIR / "frontend" / "error.html").read_text()


@app.exception_handler(StarletteHTTPException)
async def custom_404_handler(request: Request, exc: StarletteHTTPException):
    # Page 404s get the fun BJJ-themed page; /api/ 404s stay JSON so the
    # frontend's own error handling (which expects a JSON body) still works.
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return HTMLResponse(content=_ERROR_PAGE, status_code=404)
    return await http_exception_handler(request, exc)


# Serves frontend/ at the site root, same-origin with the /api routes above
# (mounted last so it doesn't shadow them).
app.mount("/", StaticFiles(directory=str(config.ROOT_DIR / "frontend"), html=True), name="frontend")

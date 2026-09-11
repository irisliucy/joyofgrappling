"""Export a finished query's ReapOutput as static JSON for GitHub Pages.

The `docs/` folder is what Pages serves when configured to build from
`main` / `docs`. This is a snapshot export, not a live feed -- see
programs.md deployment note.
"""
import json
import shutil

from . import config, store


def export_query(query_id: str):
    query = store.get_query(query_id)
    if query is None:
        raise ValueError(f"Unknown query_id: {query_id}")
    if not query["output_json"]:
        raise ValueError(f"Query {query_id} has no output yet")

    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    export_dir = config.DOCS_DIR / "exports" / query_id
    export_dir.mkdir(parents=True, exist_ok=True)

    (export_dir / "output.json").write_text(query["output_json"])

    _sync_frontend()
    _update_index({"id": query_id, "query": query["query_text"]})
    return export_dir


def _sync_frontend():
    frontend_dir = config.ROOT_DIR / "frontend"
    for name in ("index.html", "app.js", "style.css"):
        shutil.copy(frontend_dir / name, config.DOCS_DIR / name)


def _update_index(entry: dict):
    index_path = config.DOCS_DIR / "queries.json"
    existing = []
    if index_path.exists():
        existing = json.loads(index_path.read_text())
    existing = [e for e in existing if e["id"] != entry["id"]]
    existing.append(entry)
    index_path.write_text(json.dumps(existing, indent=2))

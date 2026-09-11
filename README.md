# Joy of Grappling

Reap: an autonomous BJJ research agent. Give it a position or style (and
optionally a target player), and it searches YouTube, ranks results by
relevance/authority/recency, transcribes the top ones, extracts a
structured technique graph via Claude, and scores every edge by how many
independent (and how authoritative) sources back it.

See [`programs.md`](programs.md) for the full spec: tool contracts,
authority tiers, confidence scoring, and the iteration loop.

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY and YOUTUBE_API_KEY
```

## Run

```
source .venv/bin/activate
uvicorn backend.app:app --reload
```

Then open `frontend/index.html` in a browser (or serve `frontend/` with
any static file server) — it talks to the local API at
`http://localhost:8000`.

## Publish a run to GitHub Pages

Once a query is done processing:

```
curl -X POST http://localhost:8000/api/export/<query_id>
```

This writes the run's output plus a copy of the frontend into `docs/`.
Point GitHub Pages at `docs/` on `main`, then visit
`<pages-url>/?export=<query_id>` to view that run's graph as a static
snapshot (no live backend needed to view it).

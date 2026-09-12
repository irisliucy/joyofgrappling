"""SQLite-backed knowledge store implementing store_insight's
deduplication rule and the InsightEdge aggregate.

Node dedup is name-normalization only (lowercase + strip) in v1 -- see
programs.md Open Questions for why semantic dedup is deferred.
"""
import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config, scoring
from .schemas import InsightEdge, RawExtraction, SourceRef, SourceScore, VideoMeta

SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    config_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    progress TEXT DEFAULT '',
    output_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    title TEXT,
    channel_id TEXT,
    channel_name TEXT,
    url TEXT,
    published_at TEXT,
    authority_tier INTEGER,
    caption_available INTEGER DEFAULT 0,
    PRIMARY KEY (query_id, video_id)
);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT NOT NULL,             -- hash of from+to+type
    query_id TEXT NOT NULL,
    from_position TEXT NOT NULL,
    to_position TEXT NOT NULL,
    transition_type TEXT NOT NULL,
    conditions_json TEXT DEFAULT '[]',
    grip_details_json TEXT DEFAULT '[]',
    body_cues_json TEXT DEFAULT '[]',
    source_count INTEGER DEFAULT 0,
    highest_authority_tier INTEGER DEFAULT 4,
    has_competition_footage INTEGER DEFAULT 0,
    contested INTEGER DEFAULT 0,
    contested_detail TEXT,
    first_seen TEXT,
    last_seen TEXT,
    PRIMARY KEY (id, query_id)
);

CREATE TABLE IF NOT EXISTS edge_sources (
    edge_id TEXT NOT NULL,
    query_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    video_url TEXT,
    channel_name TEXT,
    authority_tier INTEGER,
    is_competition_footage INTEGER,
    timestamp_start REAL,
    raw_quote TEXT,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    extraction_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL,
    edge_id TEXT NOT NULL,
    action TEXT NOT NULL,          -- 'up' | 'down'
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS channel_reputation (
    channel_id TEXT PRIMARY KEY,
    score INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS topic_exclusions (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,           -- normalize_name(query_text) -- exact-match scope
    video_id TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(topic, video_id)
);

CREATE TABLE IF NOT EXISTS run_logs (
    id TEXT PRIMARY KEY,
    query_id TEXT NOT NULL,
    iteration INTEGER,
    step TEXT,
    status TEXT,
    details_json TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def _normalize(name: str) -> str:
    # Collapse underscore/hyphen variants ("k_guard", "K-guard", "k guard")
    # into one canonical key -- the extraction model isn't consistent about
    # which separator it uses for the same position.
    collapsed = re.sub(r"[-_]+", " ", name.strip().lower())
    return " ".join(collapsed.split())


normalize_name = _normalize  # public alias -- loop.py needs the same rule for node ids


def edge_id_for(from_position: str, to_position: str, transition_type: str) -> str:
    key = f"{_normalize(from_position)}|{_normalize(to_position)}|{transition_type}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def create_query(query_text: str, config_dict: dict) -> str:
    query_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO queries (id, query_text, config_json, status) VALUES (?, ?, ?, 'pending')",
            (query_id, query_text, json.dumps(config_dict)),
        )
    return query_id


def update_query_status(query_id: str, status: str, progress: str = ""):
    with get_conn() as conn:
        conn.execute(
            "UPDATE queries SET status = ?, progress = ? WHERE id = ?", (status, progress, query_id)
        )


def save_output(query_id: str, output_json: str):
    with get_conn() as conn:
        conn.execute("UPDATE queries SET output_json = ? WHERE id = ?", (output_json, query_id))


def get_last_activity(query_id: str) -> str | None:
    """Timestamp of the most recent run_log entry for this query, or None
    if it never logged anything (e.g. crashed before the first step). Used
    to tell a genuinely stalled/orphaned job (backend process died mid-run,
    status frozen at "running" forever) from one that's actively working.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(created_at) as last_activity FROM run_logs WHERE query_id = ?", (query_id,)
        ).fetchone()
        return row["last_activity"] if row else None


def get_query(query_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM queries WHERE id = ?", (query_id,)).fetchone()
        return dict(row) if row else None


def log(query_id: str, iteration: int, step: str, status: str, details: dict | None = None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO run_logs (id, query_id, iteration, step, status, details_json) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), query_id, iteration, step, status, json.dumps(details or {})),
        )


def save_video(query_id: str, video: VideoMeta, source_score: SourceScore, caption_available: bool):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO videos
               (video_id, query_id, title, channel_id, channel_name, url, published_at, authority_tier, caption_available)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                video.video_id,
                query_id,
                video.title,
                video.channel_id,
                video.channel_name,
                video.url,
                video.published_at,
                source_score.authority_tier,
                int(caption_available),
            ),
        )


def queue_for_review(query_id: str, video_id: str, extraction: RawExtraction):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO review_queue (id, query_id, video_id, extraction_json) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), query_id, video_id, extraction.model_dump_json()),
        )


def store_insight(
    query_id: str, extraction: RawExtraction, source_score: SourceScore, video: VideoMeta
) -> InsightEdge:
    """Implements the dedup rule: same from+to+type merges into one edge,
    appending the new source and recomputing aggregates + confidence_label.
    """
    eid = edge_id_for(extraction.from_position, extraction.to_position, extraction.transition_type)
    now = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM edges WHERE id = ? AND query_id = ?", (eid, query_id)
        ).fetchone()

        conditions = json.loads(row["conditions_json"]) if row else []
        grip_details = json.loads(row["grip_details_json"]) if row else []
        body_cues = json.loads(row["body_cues_json"]) if row else []

        if extraction.condition and extraction.condition not in conditions:
            conditions.append(extraction.condition)
        if extraction.grip_detail and extraction.grip_detail not in grip_details:
            grip_details.append(extraction.grip_detail)
        if extraction.body_cue and extraction.body_cue not in body_cues:
            body_cues.append(extraction.body_cue)

        existing_sources = _load_sources(conn, eid, query_id)
        new_source = SourceRef(
            video_id=video.video_id,
            video_url=video.url,
            channel_name=video.channel_name,
            authority_tier=source_score.authority_tier,
            is_competition_footage=source_score.is_competition_footage,
            timestamp_start=extraction.timestamp_start,
            raw_quote=extraction.raw_quote,
        )
        already_sourced_by_video = any(s.video_id == video.video_id for s in existing_sources)
        if not already_sourced_by_video:
            conn.execute(
                """INSERT INTO edge_sources
                   (edge_id, query_id, video_id, video_url, channel_name, authority_tier,
                    is_competition_footage, timestamp_start, raw_quote, published_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    eid, query_id, video.video_id, video.url, video.channel_name,
                    source_score.authority_tier, int(source_score.is_competition_footage),
                    extraction.timestamp_start, extraction.raw_quote, video.published_at,
                ),
            )
            all_sources = existing_sources + [new_source]
        else:
            all_sources = existing_sources

        highest_tier = min([s.authority_tier for s in all_sources], default=4)
        has_competition = any(s.is_competition_footage for s in all_sources)
        first_seen = row["first_seen"] if row and row["first_seen"] else video.published_at
        last_seen = max([row["last_seen"], video.published_at]) if row and row["last_seen"] else video.published_at

        published_dates = _published_dates_for_edge(conn, eid, query_id)
        temporal_signal = scoring.compute_temporal_signal(published_dates)

        edge = InsightEdge(
            id=eid,
            from_position=extraction.from_position if not row else row["from_position"],
            to_position=extraction.to_position if not row else row["to_position"],
            transition_type=extraction.transition_type,
            conditions=conditions,
            grip_details=grip_details,
            body_cues=body_cues,
            source_count=len(all_sources),
            sources=all_sources,
            highest_authority_tier=highest_tier,
            has_competition_footage=has_competition,
            contested=bool(row["contested"]) if row else False,
            contested_detail=row["contested_detail"] if row else None,
            first_seen=first_seen,
            last_seen=last_seen,
            temporal_signal=temporal_signal,
        )
        edge.confidence_label = scoring.compute_confidence_label(edge)

        conn.execute(
            """INSERT OR REPLACE INTO edges
               (id, query_id, from_position, to_position, transition_type, conditions_json,
                grip_details_json, body_cues_json, source_count, highest_authority_tier,
                has_competition_footage, contested, contested_detail, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid, query_id, edge.from_position, edge.to_position, edge.transition_type,
                json.dumps(conditions), json.dumps(grip_details), json.dumps(body_cues),
                edge.source_count, edge.highest_authority_tier, int(edge.has_competition_footage),
                int(edge.contested), edge.contested_detail, edge.first_seen, edge.last_seen,
            ),
        )

    return edge


def _load_sources(conn, edge_id: str, query_id: str) -> list[SourceRef]:
    rows = conn.execute(
        "SELECT * FROM edge_sources WHERE edge_id = ? AND query_id = ?", (edge_id, query_id)
    ).fetchall()
    return [
        SourceRef(
            video_id=r["video_id"],
            video_url=r["video_url"],
            channel_name=r["channel_name"],
            authority_tier=r["authority_tier"],
            is_competition_footage=bool(r["is_competition_footage"]),
            timestamp_start=r["timestamp_start"],
            raw_quote=r["raw_quote"],
        )
        for r in rows
    ]


def _published_dates_for_edge(conn, edge_id: str, query_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT published_at FROM edge_sources WHERE edge_id = ? AND query_id = ?",
        (edge_id, query_id),
    ).fetchall()
    return [r["published_at"] for r in rows if r["published_at"]]


def _row_to_edge(conn, row, query_id: str) -> InsightEdge:
    sources = _load_sources(conn, row["id"], query_id)
    temporal_signal = scoring.compute_temporal_signal(
        _published_dates_for_edge(conn, row["id"], query_id)
    )
    edge = InsightEdge(
        id=row["id"],
        from_position=row["from_position"],
        to_position=row["to_position"],
        transition_type=row["transition_type"],
        conditions=json.loads(row["conditions_json"]),
        grip_details=json.loads(row["grip_details_json"]),
        body_cues=json.loads(row["body_cues_json"]),
        source_count=row["source_count"],
        sources=sources,
        highest_authority_tier=row["highest_authority_tier"],
        has_competition_footage=bool(row["has_competition_footage"]),
        contested=bool(row["contested"]),
        contested_detail=row["contested_detail"],
        first_seen=row["first_seen"] or "",
        last_seen=row["last_seen"] or "",
        temporal_signal=temporal_signal,
    )
    edge.confidence_label = scoring.compute_confidence_label(edge)
    return edge


def all_edges(query_id: str) -> list[InsightEdge]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM edges WHERE query_id = ?", (query_id,)).fetchall()
        return [_row_to_edge(conn, row, query_id) for row in rows]


def video_count(query_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) as c FROM videos WHERE query_id = ?", (query_id,)).fetchone()
        return row["c"]


def processed_video_ids(query_id: str) -> set[str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT video_id FROM videos WHERE query_id = ?", (query_id,)).fetchall()
        return {r["video_id"] for r in rows}


REPUTATION_WEIGHT = 0.05
REPUTATION_CLAMP = 0.5


def _channels_for_edge(conn, query_id: str, edge_id: str) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT v.channel_id FROM edge_sources es
           JOIN videos v ON v.video_id = es.video_id AND v.query_id = es.query_id
           WHERE es.edge_id = ? AND es.query_id = ? AND v.channel_id IS NOT NULL AND v.channel_id != ''""",
        (edge_id, query_id),
    ).fetchall()
    return [r["channel_id"] for r in rows]


def record_feedback(query_id: str, edge_id: str, action: str) -> None:
    """action: 'up' or 'down'. Nudges channel_reputation for every channel
    behind this edge's sources -- see programs.md: Human Feedback Loop.
    """
    if action not in ("up", "down"):
        raise ValueError(f"invalid feedback action: {action}")
    delta = 1 if action == "up" else -1

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO feedback (id, query_id, edge_id, action) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), query_id, edge_id, action),
        )
        for channel_id in _channels_for_edge(conn, query_id, edge_id):
            conn.execute(
                """INSERT INTO channel_reputation (channel_id, score, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(channel_id) DO UPDATE SET
                     score = score + excluded.score, updated_at = CURRENT_TIMESTAMP""",
                (channel_id, delta),
            )


def get_channel_reputation(channel_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT score FROM channel_reputation WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return row["score"] if row else 0


def get_reputation_factor(channel_id: str) -> float:
    """1.0 = neutral. See programs.md: Channel Reputation for the formula."""
    score = get_channel_reputation(channel_id)
    adjustment = max(-REPUTATION_CLAMP, min(REPUTATION_CLAMP, score * REPUTATION_WEIGHT))
    return 1.0 + adjustment


def delete_edge(query_id: str, edge_id: str) -> bool:
    """Permanently removes an edge and its sources from this query's graph,
    and records a topic exclusion for each source video -- delete is a
    topic-relevance learning signal, not just cleanup. See programs.md:
    Human Feedback Loop / Topic Exclusion.
    """
    with get_conn() as conn:
        edge_row = conn.execute("SELECT 1 FROM edges WHERE id = ? AND query_id = ?", (edge_id, query_id)).fetchone()
        if edge_row is None:
            return False

        query_row = conn.execute("SELECT query_text FROM queries WHERE id = ?", (query_id,)).fetchone()
        topic = _normalize(query_row["query_text"]) if query_row else None

        video_ids = [
            r["video_id"]
            for r in conn.execute(
                "SELECT DISTINCT video_id FROM edge_sources WHERE edge_id = ? AND query_id = ?", (edge_id, query_id)
            ).fetchall()
        ]

        conn.execute("DELETE FROM edge_sources WHERE edge_id = ? AND query_id = ?", (edge_id, query_id))
        conn.execute("DELETE FROM edges WHERE id = ? AND query_id = ?", (edge_id, query_id))

        if topic:
            for video_id in video_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO topic_exclusions (id, topic, video_id) VALUES (?, ?, ?)",
                    (str(uuid.uuid4()), topic, video_id),
                )
        return True


def get_excluded_video_ids(topic: str) -> set[str]:
    normalized_topic = _normalize(topic)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT video_id FROM topic_exclusions WHERE topic = ?", (normalized_topic,)
        ).fetchall()
        return {r["video_id"] for r in rows}


def has_any_edges(query_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM edges WHERE query_id = ? LIMIT 1", (query_id,)).fetchone()
        return row is not None


def get_current_iteration(query_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(iteration) as max_iter FROM run_logs WHERE query_id = ?", (query_id,)
        ).fetchone()
        return row["max_iter"] or 0

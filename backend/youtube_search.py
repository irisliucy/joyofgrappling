"""search(): YouTube implementation of the JoG `search` tool.

Only "youtube" is implemented in v1 (see programs.md scope decision).
Other sources are stubbed to raise SourceUnavailable so the loop can log
`source_unavailable` and continue, per the tool's fallback contract.
"""
import re
from datetime import datetime, timezone

from googleapiclient.discovery import build

from . import config
from .schemas import VideoMeta


class SourceUnavailable(Exception):
    pass


_ISO8601_DURATION_RE = re.compile(
    r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?"
)


def _parse_duration(iso_duration: str) -> int:
    match = _ISO8601_DURATION_RE.match(iso_duration or "")
    if not match:
        return 0
    parts = {k: int(v) if v else 0 for k, v in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def _build_client():
    if not config.YOUTUBE_API_KEY:
        raise RuntimeError(
            "YOUTUBE_API_KEY is not set. Add it to your .env file (see .env.example)."
        )
    return build("youtube", "v3", developerKey=config.YOUTUBE_API_KEY)


def search(query: str, source: str = "youtube", max_results: int = 5) -> list[VideoMeta]:
    if source != "youtube":
        raise SourceUnavailable(f"source '{source}' is not implemented yet")

    max_results = min(max_results, 10)
    youtube = _build_client()

    search_resp = (
        youtube.search()
        .list(q=query, part="id,snippet", type="video", order="relevance", maxResults=max_results)
        .execute()
    )

    video_ids = [item["id"]["videoId"] for item in search_resp.get("items", [])]
    if not video_ids:
        return []

    details_resp = (
        youtube.videos().list(part="statistics,contentDetails", id=",".join(video_ids)).execute()
    )
    details_by_id = {item["id"]: item for item in details_resp.get("items", [])}

    results = []
    for item in search_resp["items"]:
        vid = item["id"]["videoId"]
        snippet = item["snippet"]
        details = details_by_id.get(vid, {})
        stats = details.get("statistics", {})
        content = details.get("contentDetails", {})

        results.append(
            VideoMeta(
                video_id=vid,
                title=snippet.get("title", ""),
                channel_id=snippet.get("channelId", ""),
                channel_name=snippet.get("channelTitle", ""),
                published_at=snippet.get("publishedAt", datetime.now(timezone.utc).isoformat()),
                duration_seconds=_parse_duration(content.get("duration", "")),
                view_count=int(stats.get("viewCount", 0)),
                description=snippet.get("description", ""),
                url=f"https://www.youtube.com/watch?v={vid}",
                source="youtube",
            )
        )
    return results

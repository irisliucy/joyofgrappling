"""fetch_captions(): YouTube caption fetch, no API key needed.

Returns None on any failure (disabled, none found, etc.) per the tool's
fallback contract -- the caller falls back to title+description extraction
with low_confidence.
"""
from youtube_transcript_api import YouTubeTranscriptApi

from .schemas import Caption, CaptionSegment


def fetch_captions(video_id: str, source: str = "youtube") -> Caption | None:
    if source != "youtube":
        return None
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id)
    except Exception:
        return None

    segments = [
        CaptionSegment(
            start_seconds=snippet.start,
            end_seconds=snippet.start + snippet.duration,
            text=snippet.text,
        )
        for snippet in fetched
    ]
    if not segments:
        return None
    return Caption(video_id=video_id, language=fetched.language_code or "unknown", segments=segments)

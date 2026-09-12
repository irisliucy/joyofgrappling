"""RANK step of the Loop Protocol: score each video by
source authority x relevance x recency, take the top N.
"""
from datetime import datetime, timezone

from . import authority, config, store
from .schemas import VideoMeta


def _relevance(video: VideoMeta, query_terms: list[str]) -> float:
    haystack = f"{video.title} {video.description}".lower()
    if not query_terms:
        return 0.0
    hits = sum(1 for term in query_terms if term in haystack)
    return hits / len(query_terms)


def _recency(video: VideoMeta) -> float:
    try:
        published = datetime.fromisoformat(video.published_at.replace("Z", "+00:00"))
    except ValueError:
        return 1.0
    years = max((datetime.now(timezone.utc) - published).days / 365.25, 0)
    return 0.9**years


def rank_videos(videos: list[VideoMeta], query: str, top_n: int) -> list[tuple[VideoMeta, float]]:
    query_terms = [t for t in query.lower().split() if t]
    scored = []
    for video in videos:
        source_score = authority.score_source(video.channel_id, video)
        weight = config.TIER_WEIGHTS.get(source_score.authority_tier, config.TIER_WEIGHTS[4])
        # Human feedback (thumbs up/down) accumulates per-channel across
        # queries and nudges ranking here -- see programs.md: Channel
        # Reputation. Static Authority Table tiers remain the primary
        # signal; this is a secondary, earned adjustment on top.
        reputation_factor = store.get_reputation_factor(video.channel_id)
        score = weight * reputation_factor * _relevance(video, query_terms) * _recency(video)
        scored.append((video, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_n]

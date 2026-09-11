"""score_source: static Authority Table lookup + competition-footage
heuristic. See programs.md: Authority Table.
"""
from . import config
from .schemas import SourceScore, VideoMeta


def score_source(channel_id: str, video: VideoMeta) -> SourceScore:
    tier, matched_name = _lookup_tier(video.channel_name)
    is_competition = _looks_like_competition_footage(video, tier)

    return SourceScore(
        channel_id=channel_id,
        authority_tier=tier,
        is_competition_footage=is_competition,
        instructor_identity=matched_name,
        lineage=None,
        ruleset="unknown",
        notes="" if matched_name else "channel not in Authority Table, defaulted to tier 4",
    )


def _lookup_tier(channel_name: str) -> tuple[int, str | None]:
    lower = channel_name.lower()
    for name, tier in config.AUTHORITY_TABLE:
        if name.lower() in lower:
            return tier, name
    return config.DEFAULT_TIER, None


def _looks_like_competition_footage(video: VideoMeta, tier: int) -> bool:
    if tier != 1:
        return False
    haystack = f"{video.title} {video.description}".lower()
    return any(kw in haystack for kw in config.COMPETITION_KEYWORDS)

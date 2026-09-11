"""confidence_label decision tree, verbatim from programs.md: Confidence
Scoring. Order of the if/elif chain matters -- do not reorder.
"""
from datetime import datetime, timezone

from .schemas import ConfidenceLabel, InsightEdge


def compute_confidence_label(edge: InsightEdge) -> ConfidenceLabel:
    if edge.contested:
        return "contested"
    if edge.source_count == 1:
        return "signature"
    if all(s.authority_tier == 4 for s in edge.sources):
        return "unverified"
    if edge.has_competition_footage and edge.source_count >= 2:
        return "established"
    if edge.source_count >= 5 and edge.highest_authority_tier <= 2:
        return "established"
    if edge.source_count >= 5 and edge.temporal_signal == "rising":
        return "emerging"
    if edge.source_count >= 3 and edge.highest_authority_tier <= 2:
        return "emerging"
    return "unverified"


def compute_temporal_signal(published_dates: list[str]) -> str:
    """published_dates: ISO 8601 strings, one per source. Heuristic: not
    enough data below 3 sources; otherwise "rising" if the majority were
    published in the last 12 months, else "stable".
    """
    if len(published_dates) < 3:
        return "insufficient_data"

    now = datetime.now(timezone.utc)
    recent = 0
    for d in published_dates:
        try:
            parsed = datetime.fromisoformat(d.replace("Z", "+00:00"))
        except ValueError:
            continue
        if (now - parsed).days <= 365:
            recent += 1

    return "rising" if recent > len(published_dates) / 2 else "stable"

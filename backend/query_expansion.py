"""Query Expansion -- see programs.md.

v1 keeps rule 1 (name variants) and rule 2 (position variants) to a small
static alias table rather than an LLM guess, since a wrong alias silently
pollutes every downstream search. Rule 3 (context suffixes) and rule 4
(priority order, 12-query cap) are fully implemented.
"""
from . import config

_CONTEXT_SUFFIXES = [
    "BJJ instructional",
    "no gi grappling",
    "competition highlight",
    "breakdown",
]

# Known position aliases. Extend as needed -- deliberately small and
# explicit rather than LLM-generated.
_POSITION_ALIASES: dict[str, list[str]] = {
    "k guard": ["kesar guard", "outside k guard"],
    "outside heel hook": ["ohh", "kneebar entry outside"],
}


def _position_variants(position: str) -> list[str]:
    return _POSITION_ALIASES.get(position.strip().lower(), [])


def expand_query(position_query: str, target_player: str | None) -> list[str]:
    """Returns an ordered, deduplicated list of search strings, capped at
    MAX_EXPANDED_QUERIES_PER_ITERATION, prioritized:
    player name + position > position alone > player name alone.
    """
    ordered: list[str] = []

    def add(q: str):
        if q and q not in ordered:
            ordered.append(q)

    position_bases = [position_query, *_position_variants(position_query)]

    # priority 1: player + position
    if target_player:
        for pos in position_bases:
            add(f"{target_player} {pos}")
            for suffix in _CONTEXT_SUFFIXES:
                add(f"{target_player} {pos} {suffix}")

    # priority 2: position alone
    for pos in position_bases:
        add(pos)
        for suffix in _CONTEXT_SUFFIXES:
            add(f"{pos} {suffix}")

    # priority 3: player alone
    if target_player:
        add(target_player)
        for suffix in _CONTEXT_SUFFIXES:
            add(f"{target_player} {suffix}")

    return ordered[: config.MAX_EXPANDED_QUERIES_PER_ITERATION]

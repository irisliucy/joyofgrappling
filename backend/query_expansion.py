"""Query Expansion -- see programs.md.

v1 keeps rule 1 (name variants) and rule 2 (position variants) to a small
static alias table rather than an LLM guess, since a wrong alias silently
pollutes every downstream search.

YouTube's search.list costs 100 quota units/call against a 10,000/day
default quota (~100 searches/day, total). The original version of this
function multiplied every base query by all 4 context suffixes, so a
single iteration could reach 12 searches and a full 8-iteration run could
burn ~9,600 units -- nearly the entire daily budget on one query. This
version caps at MAX_EXPANDED_QUERIES_PER_ITERATION (now 4, see config.py)
and spends that budget on genuinely different queries (player+position,
position, player-alone, one alias) rather than near-duplicate suffix
variants, which added little relevance for 3-4x the cost.
"""
from . import config

# A single generic disambiguator, applied to at most one query per call
# (not multiplied across every base) -- just enough to bias away from
# unrelated results without multiplying the search count.
_CONTEXT_SUFFIX = "BJJ instructional"

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

    # priority 1: player + position (most specific, most valuable)
    if target_player:
        for pos in position_bases:
            add(f"{target_player} {pos}")

    # priority 2: position alone
    for pos in position_bases:
        add(pos)

    # priority 3: player alone
    if target_player:
        add(target_player)

    # Spend any remaining budget on one disambiguated variant of the
    # highest-priority query, rather than suffixing everything.
    if ordered and len(ordered) < config.MAX_EXPANDED_QUERIES_PER_ITERATION:
        add(f"{ordered[0]} {_CONTEXT_SUFFIX}")

    return ordered[: config.MAX_EXPANDED_QUERIES_PER_ITERATION]

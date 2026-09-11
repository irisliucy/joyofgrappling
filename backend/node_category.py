"""Heuristic NodeCategory classifier for a position/technique name.

Keyword-based, not exhaustive -- good enough to color/group the mindmap.
Falls back to "transition" when nothing matches, since an unclassified
node is still meaningfully "something between two other things."
"""
from .schemas import NodeCategory

_KEYWORDS: list[tuple[str, NodeCategory]] = [
    ("heel hook", "leglock"), ("kneebar", "leglock"), ("toe hold", "leglock"),
    ("toehold", "leglock"), ("ashi", "leglock"), ("saddle", "leglock"),
    ("50/50", "leglock"), ("leg lock", "leglock"), ("straight ankle", "leglock"),
    ("estima lock", "leglock"), ("calf slicer", "leglock"),

    ("mount", "mount"), ("s-mount", "mount"), ("high mount", "mount"),

    ("back control", "back_control"), ("back mount", "back_control"),
    ("back take", "back_control"), ("rear naked", "back_control"),
    ("seatbelt", "back_control"),

    ("choke", "submission"), ("armbar", "submission"), ("kimura", "submission"),
    ("americana", "submission"), ("guillotine", "submission"),
    ("triangle", "submission"), ("omoplata", "submission"), ("darce", "submission"),
    ("d'arce", "submission"), ("anaconda", "submission"), ("bow and arrow", "submission"),
    ("gogoplata", "submission"), ("ezekiel", "submission"),

    ("side control", "top_control"), ("knee on belly", "top_control"),
    ("north south", "top_control"), ("crucifix", "top_control"),

    ("guard", "guard"),

    ("takedown", "takedown"), ("throw", "takedown"), ("trip", "takedown"),
    ("double leg", "takedown"), ("single leg", "takedown"), ("pull guard", "takedown"),
]


def classify_category(name: str) -> NodeCategory:
    lower = name.lower()
    for keyword, category in _KEYWORDS:
        if keyword in lower:
            return category
    return "transition"

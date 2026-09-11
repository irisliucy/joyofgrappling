"""extract_techniques(): windowed transcript -> LLM -> RawExtraction[].

Window protocol: ~300-word windows with 50-word overlap (see programs.md).
The extraction prompt is sent verbatim, per spec -- do not edit its wording
without bumping the Output Contract Version in programs.md.
"""
import json

import anthropic

from . import config
from .schemas import Caption, CaptionSegment, RawExtraction

_EXTRACTION_PROMPT = """\
You are a BJJ technique extraction engine. Given the transcript segment
below, extract every technique transition mentioned.

For each transition output a JSON object with these exact keys:
from_position, to_position, transition_type, condition, grip_detail,
body_cue, timestamp_start, confidence, needs_review, raw_quote.

Rules:
- from_position and to_position must be named BJJ positions or submissions.
  Never use pronouns or vague terms ("this", "here", "that position").
  If the position is unclear from context, set needs_review: true and use
  your best guess with low confidence.
- transition_type must be one of: finish, sweep, back_take, escape, pass,
  entry, counter, re_counter.
- condition is the trigger: what the opponent does or what body state exists
  that makes this transition available. null if not stated.
- raw_quote must be the exact words from the transcript that support this
  extraction. Max 40 words.
- If nothing extractable is in this segment, return an empty array [].
- Output only valid JSON. No prose, no markdown, no preamble.

Current position context: {position_context}
Source authority tier: {authority_tier}

Transcript segment:
{segment_text}
"""


class Window:
    def __init__(self, text: str, timestamp_start: float):
        self.text = text
        self.timestamp_start = timestamp_start


def chunk_segments(
    segments: list[CaptionSegment],
    window_words: int = config.WINDOW_WORD_COUNT,
    overlap_words: int = config.OVERLAP_WORD_COUNT,
) -> list[Window]:
    words: list[tuple[str, float]] = []
    for seg in segments:
        for word in seg.text.split():
            words.append((word, seg.start_seconds))

    if not words:
        return []

    windows = []
    step = max(window_words - overlap_words, 1)
    for start_idx in range(0, len(words), step):
        chunk = words[start_idx : start_idx + window_words]
        if not chunk:
            continue
        text = " ".join(w for w, _ in chunk)
        timestamp_start = chunk[0][1]
        windows.append(Window(text=text, timestamp_start=timestamp_start))
        if start_idx + window_words >= len(words):
            break
    return windows


def extract_techniques(
    window: Window, position_context: str, authority_tier: int
) -> list[RawExtraction]:
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to your .env file (see .env.example)."
        )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    prompt = _EXTRACTION_PROMPT.format(
        position_context=position_context or "none",
        authority_tier=authority_tier,
        segment_text=window.text,
    )

    response = client.messages.create(
        model=config.EXTRACTION_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = "".join(block.text for block in response.content if block.type == "text")
    items = _parse_json_array(raw_text)

    extractions = []
    for item in items:
        _sanitize_extraction(item, window.timestamp_start)
        extractions.append(RawExtraction.model_validate(item))
    return extractions


def _sanitize_extraction(item: dict, fallback_timestamp: float) -> None:
    """The extraction model doesn't always follow the prompt's literal
    contract exactly (e.g. null timestamps, numeric confidence scores) --
    coerce those into the schema's expected shape rather than dropping the
    whole extraction.
    """
    if item.get("timestamp_start") is None:
        item["timestamp_start"] = fallback_timestamp

    confidence = item.get("confidence")
    if isinstance(confidence, (int, float)):
        if confidence >= 0.7:
            item["confidence"] = "high"
        elif confidence >= 0.4:
            item["confidence"] = "medium"
        else:
            item["confidence"] = "low"
    elif confidence not in ("high", "medium", "low"):
        item["confidence"] = "medium"


def _parse_json_array(raw_text: str) -> list[dict]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    return data if isinstance(data, list) else []

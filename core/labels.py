"""Label maps and BIO <-> span conversion shared by both models.

Each sentence has two independent BIO layers (Skill, Knowledge), so a token may
belong to a span in both layers. Spans are (start, end) word indices, end exclusive.
"""
from __future__ import annotations

HEADS: tuple[str, ...] = ("skill", "knowledge")
LABELS: tuple[str, ...] = ("O", "B", "I")
LABEL2ID: dict[str, int] = {label: i for i, label in enumerate(LABELS)}
ID2LABEL: dict[int, str] = {i: label for label, i in LABEL2ID.items()}
IGNORE_INDEX = -100  # positions excluded from the loss (padding, special tokens, non-first subwords)

Span = tuple[int, int]


def bio_to_spans(tags: list[str]) -> list[Span]:
    """Convert one BIO sequence to spans.

    An `I` that does not continue a span (after `O` or at position 0) starts a new
    span. This matches seqeval's default (non-strict) CoNLL behaviour, so model
    output with a missing `B` is still counted instead of silently dropped.
    """
    spans: list[Span] = []
    start: int | None = None
    for i, tag in enumerate(tags):
        if tag == "B" or (tag == "I" and start is None):
            if start is not None:
                spans.append((start, i))
            start = i
        elif tag == "O":
            if start is not None:
                spans.append((start, i))
            start = None
        elif tag != "I":
            raise ValueError(f"unknown tag {tag!r} at position {i}")
    if start is not None:
        spans.append((start, len(tags)))
    return spans


def spans_to_bio(spans: list[Span], length: int) -> list[str]:
    """Inverse of bio_to_spans for non-overlapping spans within one layer."""
    tags = ["O"] * length
    for start, end in sorted(spans):
        if not 0 <= start < end <= length:
            raise ValueError(f"span {(start, end)} out of range for length {length}")
        if any(t != "O" for t in tags[start:end]):
            raise ValueError(f"span {(start, end)} overlaps another span in the same layer")
        tags[start] = "B"
        for i in range(start + 1, end):
            tags[i] = "I"
    return tags

"""Classify span errors for the report: false positive, false negative, boundary error.

boundary : predicted and gold span of the same type overlap but start/end differ
fp       : predicted span that overlaps no gold span of its type
fn       : gold span that overlaps no predicted span of its type
"""
from __future__ import annotations

from .labels import HEADS, bio_to_spans


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def classify_errors(tokens: list[list[str]], gold: dict[str, list[list[str]]],
                    pred: dict[str, list[list[str]]]) -> list[dict]:
    errors = []
    for head in HEADS:
        for sid, words in enumerate(tokens):
            g = set(bio_to_spans(gold[head][sid]))
            p = set(bio_to_spans(pred[head][sid]))
            text = lambda s: " ".join(words[s[0]: s[1]])  # noqa: E731
            for ps in sorted(p - g):
                partners = [gs for gs in g - p if _overlaps(ps, gs)]
                kind = "boundary" if partners else "fp"
                errors.append({"type": kind, "head": head, "sentence_id": sid, "pred": text(ps),
                               "gold": text(partners[0]) if partners else None, "sentence": " ".join(words)})
            for gs in sorted(g - p):
                if not any(_overlaps(gs, ps) for ps in p - g):
                    errors.append({"type": "fn", "head": head, "sentence_id": sid, "pred": None,
                                   "gold": text(gs), "sentence": " ".join(words)})
    return errors

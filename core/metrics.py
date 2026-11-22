"""Entity-level precision / recall / F1 shared by both models.

A predicted span counts as correct only if its sentence, start, end and type
(skill or knowledge) all match a gold span. `overall` is micro-averaged over
both types.
"""
from __future__ import annotations

from .labels import HEADS, bio_to_spans


def _prf(tp: int, n_pred: int, n_gold: int) -> dict[str, float | int]:
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": p, "recall": r, "f1": f, "tp": tp, "n_pred": n_pred, "n_gold": n_gold}


def span_sets(tags_by_head: dict[str, list[list[str]]]) -> set[tuple[int, int, int, str]]:
    """{head: [sentence tags, ...]} -> {(sentence, start, end, head)}."""
    out = set()
    for head, sentences in tags_by_head.items():
        for sid, tags in enumerate(sentences):
            for start, end in bio_to_spans(tags):
                out.add((sid, start, end, head))
    return out


def entity_scores(gold: dict[str, list[list[str]]], pred: dict[str, list[list[str]]]) -> dict[str, dict]:
    """Return per-head and overall scores. Both dicts map head -> list of BIO sequences."""
    for head in HEADS:
        if len(gold[head]) != len(pred[head]):
            raise ValueError(f"{head}: {len(gold[head])} gold vs {len(pred[head])} predicted sentences")
        for i, (g, p) in enumerate(zip(gold[head], pred[head])):
            if len(g) != len(p):
                raise ValueError(f"{head} sentence {i}: {len(g)} gold vs {len(p)} predicted tags")
    g_spans, p_spans = span_sets(gold), span_sets(pred)
    scores = {}
    for head in HEADS:
        g = {s for s in g_spans if s[3] == head}
        p = {s for s in p_spans if s[3] == head}
        scores[head] = _prf(len(g & p), len(p), len(g))
    scores["overall"] = _prf(len(g_spans & p_spans), len(p_spans), len(g_spans))
    return scores

import random

import pytest
from seqeval.metrics import f1_score, precision_score, recall_score

from core.labels import bio_to_spans, spans_to_bio
from core.metrics import entity_scores


def test_bio_to_spans_basic():
    assert bio_to_spans(["O", "B", "I", "O", "B", "B", "I"]) == [(1, 3), (4, 5), (5, 7)]


def test_bio_to_spans_orphan_i_starts_span():
    assert bio_to_spans(["I", "I", "O", "I"]) == [(0, 2), (3, 4)]


def test_bio_to_spans_span_at_end_and_empty():
    assert bio_to_spans(["O", "B", "I"]) == [(1, 3)]
    assert bio_to_spans([]) == []


def test_unknown_tag_raises():
    with pytest.raises(ValueError):
        bio_to_spans(["O", "B-SKILL"])


def test_spans_roundtrip():
    tags = ["B", "I", "O", "B", "O", "B", "I", "I"]
    assert spans_to_bio(bio_to_spans(tags), len(tags)) == tags


def test_overlap_across_heads_is_kept():
    # "Python" is both a skill and knowledge span: both must be scored independently.
    gold = {"skill": [["B", "I", "O"]], "knowledge": [["B", "O", "O"]]}
    pred = {"skill": [["B", "I", "O"]], "knowledge": [["O", "O", "O"]]}
    s = entity_scores(gold, pred)
    assert s["skill"]["f1"] == 1.0
    assert s["knowledge"]["recall"] == 0.0
    assert s["overall"]["tp"] == 1 and s["overall"]["n_gold"] == 2


def test_boundary_error_is_not_a_match():
    gold = {"skill": [["B", "I", "I"]], "knowledge": [["O", "O", "O"]]}
    pred = {"skill": [["B", "I", "O"]], "knowledge": [["O", "O", "O"]]}
    assert entity_scores(gold, pred)["skill"]["tp"] == 0


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        entity_scores({"skill": [["O"]], "knowledge": [["O"]]}, {"skill": [["O", "O"]], "knowledge": [["O"]]})


def test_matches_seqeval_on_random_tags():
    rng = random.Random(0)
    def rand_sent(n):
        return [rng.choice("OOOBI") for _ in range(n)]
    lengths = [rng.randint(1, 30) for _ in range(300)]
    gold = {h: [rand_sent(n) for n in lengths] for h in ("skill", "knowledge")}
    pred = {h: [rand_sent(n) for n in lengths] for h in ("skill", "knowledge")}
    ours = entity_scores(gold, pred)
    for head in ("skill", "knowledge"):
        typed = lambda seqs: [[t if t == "O" else f"{t}-{head.upper()}" for t in s] for s in seqs]
        g, p = typed(gold[head]), typed(pred[head])
        assert ours[head]["precision"] == pytest.approx(precision_score(g, p))
        assert ours[head]["recall"] == pytest.approx(recall_score(g, p))
        assert ours[head]["f1"] == pytest.approx(f1_score(g, p))

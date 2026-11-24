"""Sentence-BERT fallback for unmatched spans, and the scheduled job import."""
import pytest
import torch
from fastapi.testclient import TestClient

from core.embed_normalize import EmbeddingNormalizer
from core.extractor import SkillExtractor
from core.labels import HEADS

TOKEN = "test-admin-token"


class FakeEncoder:
    """Stands in for SentenceTransformer: texts that share a keyword get the same unit vector,
    texts without a keyword get a zero vector (similarity 0 to everything)."""

    KEYS = ["postgres", "sql", "docker", "contain"]

    def encode(self, texts, convert_to_tensor=True, normalize_embeddings=True, show_progress_bar=False):
        out = []
        for t in texts:
            v = torch.zeros(len(self.KEYS))
            hit = next((i for i, k in enumerate(self.KEYS) if k in t.lower()), None)
            if hit is not None:
                v[2 if hit == 3 else hit] = 1.0  # "contain..." points at Docker
            out.append(v)
        return torch.stack(out)


def tag_spans(spans_by_word):
    """Tagger that marks given words as one-word knowledge spans."""
    def tagger(sentences):
        tags = {h: [["O"] * len(s) for s in sentences] for h in HEADS}
        for i, s in enumerate(sentences):
            for j, w in enumerate(s):
                if w in spans_by_word:
                    tags["knowledge"][i][j] = "B"
        return tags
    return tagger


def test_embedding_maps_only_unmatched_spans_above_threshold():
    emb = EmbeddingNormalizer(model=FakeEncoder(), threshold=0.75)
    hits = emb.map_many(["containerisation", "teamwork", "a very long description of the work we do"])
    assert hits[0]["skill"] == "Docker" and hits[0]["score"] == pytest.approx(1.0)
    assert hits[1]["skill"] is None
    assert hits[2]["skill"] is None and hits[2]["score"] is None  # too long to be a skill name

    ex = SkillExtractor(tag_spans({"containerisation", "teamwork", "Python"}), model_name="fake", embedder=emb)
    out = ex.extract("We use containerisation and Python. Good teamwork.")
    by_text = {r["text"]: r for r in out["requirements"]}
    assert by_text["containerisation"]["normalized"] == ["Docker"]
    assert by_text["containerisation"]["normalized_by"] == "embedding"
    assert by_text["Python"]["normalized_by"] == "dictionary"
    assert by_text["teamwork"]["normalized"] == [] and "teamwork" in out["unmatched"]
    assert "Docker" in out["skills"] and out["embedding"]["threshold"] == 0.75

    plain = SkillExtractor(tag_spans({"containerisation", "Python"}), model_name="fake")
    assert "Docker" not in plain.extract("We use containerisation and Python.")["skills"]


def test_parse_auto_import():
    from api.main import parse_auto_import

    assert parse_auto_import("greenhouse:gitlab, lever:acme,bad,workday:x, greenhouse:") == [
        ("greenhouse", "gitlab"), ("lever", "acme")]
    assert parse_auto_import(None) == []


def test_scheduled_import_logs_and_continues(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLLENS_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("SKILLLENS_SKIP_MODEL", "1")
    monkeypatch.setenv("SKILLLENS_ADMIN_TOKEN", TOKEN)
    from api import main
    from core.jobs import JobImportError

    def fake_greenhouse(board, limit=30, timeout=15.0):
        if board == "broken":
            raise JobImportError("job.board_not_found")
        return [{"source": "greenhouse", "source_id": f"{board}-1", "title": "Backend Engineer", "company": board,
                 "location": "Remote", "description": "Python and SQL.", "url": "https://example.com/1"}]

    from api import state as api_state

    monkeypatch.setattr(api_state, "fetch_greenhouse", fake_greenhouse)
    with TestClient(main.app) as c:
        main.state.auto_import = {"boards": [("greenhouse", "broken"), ("greenhouse", "acme")],
                                  "every_hours": 24, "last_run": None, "next_run": None}
        main.run_scheduled_imports()
        log = c.get("/admin/api/imports", headers={"X-Admin-Token": TOKEN}).json()
        assert [(e["board"], e["status"]) for e in log[:2]] == [("acme", "ok"), ("broken", "error")]
        assert log[0]["message"] == "scheduled" and log[0]["created"] == 1
        stats = c.get("/admin/api/stats", headers={"X-Admin-Token": TOKEN}).json()
        assert stats["auto_import"]["boards"] == ["greenhouse:broken", "greenhouse:acme"]
        assert stats["auto_import"]["last_run"] is not None
        main.state.auto_import = {}


def test_gold_match_metrics():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("gold_match", Path("scripts/gold_match.py"))
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    assert g.ndcg([2, 1, 0], 5) == pytest.approx(1.0)
    assert g.ndcg([0, 0, 2], 5) < g.ndcg([0, 2, 0], 5) < 1.0
    assert g.ndcg([0, 0], 5) is None
    assert g.spearman([1, 2, 3], [0, 1, 2]) == pytest.approx(1.0)
    assert g.spearman([1, 2, 3], [2, 1, 0]) == pytest.approx(-1.0)
    assert g.spearman([1, 1, 1], [0, 1, 2]) is None


def test_imported_jobs_without_technical_skills_are_not_listed():
    from api.main import is_listed

    job = lambda source, ex: {"source": source, "extraction": ex}  # noqa: E731
    assert is_listed(job("greenhouse", {"skills": ["Python"]}))
    assert not is_listed(job("greenhouse", {"skills": []}))      # e.g. a sales role
    assert is_listed(job("greenhouse", None))                     # not read yet: shown until it is
    assert is_listed(job("demo", {"skills": []})) and is_listed(job("manual", {"skills": []}))

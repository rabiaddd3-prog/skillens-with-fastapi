"""Sentence-BERT fallback for model spans the dictionary cannot name.

The dictionary only recognises its own aliases, so a span like "relational
databases" or "REST" stays unmatched and never reaches the job match. Here every
alias of every canonical skill is embedded once; an unmatched span is mapped to
the skill of its most similar alias if the cosine similarity reaches `threshold`.
Mapped requirements are marked `normalized_by="embedding"` with their score, so
the UI and the report can always tell them apart from dictionary matches.

Optional: if sentence-transformers or the model is not available the app runs
without it (see `load_default`).
"""
from __future__ import annotations

import os

from .skills import SkillDictionary, default_dictionary

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_THRESHOLD = 0.75
MAX_WORDS = 6  # longer spans are task descriptions ("build secure, reliable features"), not skill names


class EmbeddingNormalizer:
    def __init__(self, dictionary: SkillDictionary | None = None, model_name: str = DEFAULT_MODEL,
                 threshold: float = DEFAULT_THRESHOLD, device: str | None = None, model=None):
        self.dictionary = dictionary or default_dictionary()
        self.model_name = model_name
        self.threshold = threshold
        if model is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name, device=device)
        self.model = model
        self.labels: list[tuple[str, str]] = []  # (alias text, canonical skill)
        for name in self.dictionary.skills:
            self.labels.append((name, name))
        for name, aliases in self.dictionary.aliases.items():
            for a in aliases:
                if a.lower() != name.lower():
                    self.labels.append((a, name))
        self._label_vecs = self._encode([a for a, _ in self.labels])
        self._cache: dict[str, dict] = {}

    def _encode(self, texts: list[str]):
        return self.model.encode(texts, convert_to_tensor=True, normalize_embeddings=True,
                                 show_progress_bar=False)

    def map_many(self, spans: list[str]) -> list[dict]:
        """[{text, skill|None, score, alias}] in input order. Spans longer than MAX_WORDS are skipped."""
        todo = [s for s in dict.fromkeys(spans) if s not in self._cache]
        short = [s for s in todo if 0 < len(s.split()) <= MAX_WORDS]
        for s in todo:
            if s not in short:
                self._cache[s] = {"text": s, "skill": None, "score": None, "alias": None}
        if short:
            sims = self._encode(short) @ self._label_vecs.T
            for s, row in zip(short, sims):
                score, idx = float(row.max()), int(row.argmax())
                alias, skill = self.labels[idx]
                self._cache[s] = {"text": s, "skill": skill if score >= self.threshold else None,
                                  "score": round(score, 4), "alias": alias}
        return [dict(self._cache[s]) for s in spans]

    def map(self, span: str) -> dict:
        return self.map_many([span])[0]


def load_default(dictionary: SkillDictionary | None = None, device: str | None = None) -> EmbeddingNormalizer | None:
    """The app's normaliser, or None if disabled (SKILLLENS_EMBED=0) or unavailable."""
    if os.environ.get("SKILLLENS_EMBED", "1") == "0":
        return None
    try:
        threshold = float(os.environ.get("SKILLLENS_EMBED_THRESHOLD", DEFAULT_THRESHOLD))
        return EmbeddingNormalizer(dictionary, threshold=threshold, device=device)
    except Exception as exc:  # missing package, no network for the first download, ...
        print(f"Sentence-BERT normaliser not loaded ({type(exc).__name__}: {exc}); dictionary only.")
        return None

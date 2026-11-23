"""Raw English job text -> Skill/Knowledge spans with character offsets.

Steps: split into sentences -> split into words (keeping offsets) -> tag with
the trained model -> turn BIO tags into spans -> map each span to canonical
skills via the dictionary. Repeated mentions are merged into one requirement.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .labels import HEADS, bio_to_spans
from .skills import SkillDictionary, default_dictionary

# Keep technical tokens whole: C#, C++, Node.js, CI/CD, .NET; split other punctuation off.
_WORD = re.compile(r"\.?[A-Za-z0-9][A-Za-z0-9+#.\-/']*[A-Za-z0-9+#]|\.?[A-Za-z0-9][+#]*|[^\w\s]")
_PUNCT = re.compile(r"[^\w\s]")
_SENT_END =re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])|\n\s*[-*•]?\s*|\n")


def split_sentences(text: str) -> list[tuple[str, int]]:
    """(sentence, start offset) pairs. Bullet lines and blank lines also end a sentence."""
    out, pos = [], 0
    for m in _SENT_END.finditer(text):
        if text[pos: m.start()].strip():
            out.append((text[pos: m.start()], pos))
        pos = m.end()
    if text[pos:].strip():
        out.append((text[pos:], pos))
    return out


def tokenize_words(sentence: str, offset: int = 0) -> list[tuple[str, int, int]]:
    words = []
    for m in _WORD.finditer(sentence):
        w = m.group(0)
        # A trailing sentence period is not part of the word ("Python." -> "Python", ".").
        if len(w) > 1 and w.endswith(".") and not w.startswith("."):
            words.append((w[:-1], offset + m.start(), offset + m.end() - 1))
            words.append((".", offset + m.end() - 1, offset + m.end()))
        else:
            words.append((w, offset + m.start(), offset + m.end()))
    return words


@dataclass
class Mention:
    text: str
    type: str          # "skill" or "knowledge"
    start: int         # character offsets in the original text
    end: int
    normalized: list[str]
    found_by: str = "model"
    normalized_by: str | None = None   # "dictionary" | "embedding" | None (not matched)
    norm_score: float | None = None    # cosine similarity when normalized_by == "embedding"


@dataclass
class Requirement:
    text: str
    type: str
    normalized: list[str]
    found_by: str
    normalized_by: str | None = None
    norm_score: float | None = None
    mentions: list[tuple[int, int]] = field(default_factory=list)


class SkillExtractor:
    """Wraps a trained tagger. `tagger(sentences) -> {head: [tags]}` keeps the model swappable."""

    def __init__(self, tagger, dictionary: SkillDictionary | None = None, model_name: str = "distilbert",
                 embedder=None):
        self.tagger = tagger
        self.dictionary = dictionary or default_dictionary()
        self.model_name = model_name
        self.embedder = embedder  # optional core.embed_normalize.EmbeddingNormalizer

    @classmethod
    def from_checkpoint(cls, path: str | Path, kind: str = "distilbert", device="cpu") -> "SkillExtractor":
        if kind == "distilbert":
            from . import distilbert

            model, tok, meta = distilbert.load_checkpoint(path, device)
            tagger = lambda s: distilbert.predict_tags(model, tok, s, max_length=meta["max_length"], device=device)  # noqa: E731
        elif kind == "bilstm":
            from . import bilstm

            model, vocab, _ = bilstm.load_checkpoint(path, device)
            tagger = lambda s: bilstm.predict_tags(model, vocab, s, device=device)  # noqa: E731
        else:
            raise ValueError(f"unknown model kind {kind!r}")
        return cls(tagger, model_name=kind)

    def mentions(self, text: str, use_dictionary: bool = True) -> list[Mention]:
        sentences = [tokenize_words(s, off) for s, off in split_sentences(text)]
        sentences = [s for s in sentences if s]
        tags = self.tagger([[w for w, _, _ in s] for s in sentences]) if sentences else {h: [] for h in HEADS}
        found: list[Mention] = []
        for head in HEADS:
            for words, seq in zip(sentences, tags[head]):
                for a, b in bio_to_spans(seq):
                    # Drop punctuation the model tagged at the span edges ("REST APIs." -> "REST APIs").
                    while a < b and _PUNCT.fullmatch(words[a][0]):
                        a += 1
                    while b > a and _PUNCT.fullmatch(words[b - 1][0]):
                        b -= 1
                    if a == b:
                        continue
                    start, end = words[a][1], words[b - 1][2]
                    span = text[start:end]
                    norm = self.dictionary.normalize(span)
                    found.append(Mention(span, head, start, end, norm, normalized_by="dictionary" if norm else None))
        if self.embedder is not None:
            # Spans the dictionary cannot name get the nearest skill alias, if similar enough.
            open_spans = [m for m in found if not m.normalized]
            for m, hit in zip(open_spans, self.embedder.map_many([m.text for m in open_spans])):
                if hit["skill"]:
                    m.normalized, m.normalized_by, m.norm_score = [hit["skill"]], "embedding", hit["score"]
        if use_dictionary:
            # Dictionary hits the model missed are added but flagged, never silently merged.
            for m in self.dictionary.find(text):
                if not any(x.start <= m.start and m.end <= x.end for x in found):
                    found.append(Mention(m.text, "knowledge", m.start, m.end, [m.skill], "dictionary", "dictionary"))
        return sorted(found, key=lambda m: (m.start, m.type))

    def extract(self, text: str, use_dictionary: bool = True) -> dict:
        mentions = self.mentions(text, use_dictionary)
        merged: dict[tuple, Requirement] = {}
        for m in mentions:
            key = (m.type, tuple(m.normalized) if m.normalized else m.text.lower())
            if key not in merged:
                merged[key] = Requirement(m.text, m.type, m.normalized, m.found_by, m.normalized_by, m.norm_score)
            merged[key].mentions.append((m.start, m.end))
        requirements = list(merged.values())
        skills = []
        for r in requirements:
            for s in r.normalized:
                if s not in skills:
                    skills.append(s)
        return {
            "model": self.model_name,
            "dictionary_version": self.dictionary.version,
            "embedding": ({"model": self.embedder.model_name, "threshold": self.embedder.threshold}
                          if self.embedder is not None else None),
            "mentions": [asdict(m) for m in mentions],
            "requirements": [asdict(r) for r in requirements],
            "skills": skills,
            "unmatched": [r.text for r in requirements if not r.normalized],
        }

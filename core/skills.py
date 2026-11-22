"""Skill dictionary: alias matching and normalisation to canonical names.

Used for CV skill detection and to map model-extracted job spans to canonical
skills. Matching respects token boundaries, so "Java" never matches inside
"JavaScript" and "JS" / "JavaScript" both normalise to "JavaScript".
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "skills.json"
# Characters that continue a technical token: "C" in "C#", "Java" in "JavaScript".
_EDGE = r"A-Za-z0-9+#"


@dataclass(frozen=True)
class Skill:
    name: str
    category: str
    topic: str | None


@dataclass(frozen=True)
class Match:
    skill: str
    text: str
    start: int
    end: int


class SkillDictionary:
    def __init__(self, path: str | Path = DATA):
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        # Changes whenever the dictionary file changes; cached job extractions compare against it.
        self.version = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        self.topics: dict[str, str] = data["topics"]
        self.skills: dict[str, Skill] = {}
        patterns = []
        for entry in data["skills"]:
            skill = Skill(entry["name"], entry["category"], entry["topic"])
            if skill.name in self.skills:
                raise ValueError(f"duplicate skill {skill.name}")
            if skill.topic is not None and skill.topic not in self.topics:
                raise ValueError(f"{skill.name}: unknown topic {skill.topic}")
            self.skills[skill.name] = skill
            flags = 0 if entry.get("case_sensitive") else re.IGNORECASE
            for alias in entry["aliases"]:
                body = r"\s+".join(re.escape(part) for part in alias.split())
                patterns.append((len(alias), re.compile(rf"(?<![{_EDGE}]){body}(?![{_EDGE}])", flags), skill.name))
        # Longer aliases first so "SQL Server" wins over "SQL" on the same characters.
        self._patterns = sorted(patterns, key=lambda p: -p[0])
        self._by_lower = {name.lower(): name for name in self.skills}

    def find(self, text: str) -> list[Match]:
        """All non-overlapping skill mentions in `text`, in reading order."""
        taken: list[tuple[int, int]] = []
        found: list[Match] = []
        for _, pattern, name in self._patterns:
            for m in pattern.finditer(text):
                if any(m.start() < e and s < m.end() for s, e in taken):
                    continue
                taken.append((m.start(), m.end()))
                found.append(Match(name, m.group(0), m.start(), m.end()))
        return sorted(found, key=lambda m: m.start)

    def normalize(self, text: str) -> list[str]:
        """Canonical skills mentioned in a phrase, de-duplicated, in order."""
        seen: list[str] = []
        for m in self.find(text):
            if m.skill not in seen:
                seen.append(m.skill)
        return seen

    def canonical(self, name: str) -> str | None:
        """Exact canonical name for user-entered text ('python' -> 'Python'), else alias lookup."""
        if name.strip().lower() in self._by_lower:
            return self._by_lower[name.strip().lower()]
        hits = self.normalize(name)
        return hits[0] if len(hits) == 1 else None

    def topic_of(self, skill: str) -> str | None:
        s = self.skills.get(skill)
        return s.topic if s else None


@lru_cache(maxsize=1)
def default_dictionary() -> SkillDictionary:
    return SkillDictionary()

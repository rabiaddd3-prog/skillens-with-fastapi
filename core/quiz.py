"""Multiple-choice quiz: topic-based selection, server-side answer key, per-topic scoring.

Correct answers never leave the server before submission: `start` returns
questions without the key, `submit` scores them and only then reveals answers
and explanations.
"""
from __future__ import annotations

import json
import random
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

BANK_FILE = Path(__file__).resolve().parents[1] / "data" / "quiz_bank.json"
SESSION_TTL_SECONDS = 2 * 60 * 60
REQUIRED_FIELDS = ("id", "topic", "skill", "difficulty", "question", "options", "answer", "explanation")

# Career level chosen in the UI -> question difficulty in the bank.
LEVELS = {"junior": "easy", "mid": "medium", "senior": "hard"}
DIFFICULTY_LEVEL = {v: k for k, v in LEVELS.items()}
# Order in which difficulties are used when the chosen level runs out of questions for a topic.
FALLBACK = {"junior": ("easy", "medium", "hard"), "mid": ("medium", "easy", "hard"), "senior": ("hard", "medium", "easy")}


class QuizError(ValueError):
    """User-facing quiz problem."""


def load_bank(path: str | Path = BANK_FILE) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    questions, ids = data["questions"], set()
    for q in questions:
        missing = [f for f in REQUIRED_FIELDS if f not in q]
        if missing:
            raise ValueError(f"question {q.get('id')}: missing {missing}")
        if q["id"] in ids:
            raise ValueError(f"duplicate question id {q['id']}")
        if not 0 <= q["answer"] < len(q["options"]) or len(q["options"]) < 2:
            raise ValueError(f"question {q['id']}: bad options/answer")
        if q["difficulty"] not in DIFFICULTY_LEVEL:
            raise ValueError(f"question {q['id']}: difficulty must be easy, medium or hard")
        ids.add(q["id"])
    return questions


@dataclass
class Session:
    questions: list[dict]
    level: str = "mid"
    created: float = field(default_factory=time.time)
    submitted: bool = False


class QuizEngine:
    def __init__(self, bank: list[dict] | None = None, seed: int | None = None):
        self.bank = bank if bank is not None else load_bank()
        self.by_topic: dict[str, list[dict]] = {}
        for q in self.bank:
            self.by_topic.setdefault(q["topic"], []).append(q)
        self.rng = random.Random(seed)
        self.sessions: dict[str, Session] = {}

    def topics(self) -> dict[str, int]:
        return {t: len(qs) for t, qs in sorted(self.by_topic.items())}

    def start(self, topics: list[str], total: int = 25, level: str = "mid") -> dict:
        self._expire()
        topics = [t for t in dict.fromkeys(topics)]
        unknown = [t for t in topics if t not in self.by_topic]
        if unknown:
            raise QuizError(f"No questions for topic(s): {', '.join(unknown)}.")
        if not topics:
            raise QuizError("Choose at least one quiz topic.")
        if total < 1:
            raise QuizError("The quiz needs at least one question.")
        if level not in LEVELS:
            raise QuizError(f"Unknown level {level!r}; use junior, mid or senior.")
        # Spread questions evenly over topics. Within a topic take the chosen level first, then the
        # nearest levels, so a short level pool is topped up rather than giving a shorter quiz.
        share, extra = divmod(total, len(topics))
        picked, from_other_levels = [], 0
        for i, t in enumerate(topics):
            want = share + (1 if i < extra else 0)
            for difficulty in FALLBACK[level]:
                if want <= 0:
                    break
                pool = [q for q in self.by_topic[t] if q["difficulty"] == difficulty]
                take = self.rng.sample(pool, min(want, len(pool)))
                if difficulty != LEVELS[level]:
                    from_other_levels += len(take)
                picked += take
                want -= len(take)
        self.rng.shuffle(picked)
        # Shuffle answer options per session so the correct answer's position carries no signal.
        picked = [self._shuffle_options(q) for q in picked]
        sid = secrets.token_urlsafe(16)
        self.sessions[sid] = Session(picked, level=level)
        public = [{"id": q["id"], "topic": q["topic"], "skill": q["skill"], "difficulty": q["difficulty"],
                   "level": DIFFICULTY_LEVEL[q["difficulty"]], "question": q["question"], "options": q["options"]}
                  for q in picked]
        return {"session_id": sid, "questions": public, "requested": total, "count": len(public),
                "level": level, "from_other_levels": from_other_levels}

    def _shuffle_options(self, q: dict) -> dict:
        order = list(range(len(q["options"])))
        self.rng.shuffle(order)
        return {**q, "options": [q["options"][i] for i in order], "answer": order.index(q["answer"])}

    def submit(self, session_id: str, answers: dict[str, int]) -> dict:
        self._expire()
        s = self.sessions.get(session_id)
        if s is None:
            raise QuizError("Quiz session not found or expired. Start a new quiz.")
        if s.submitted:
            raise QuizError("This quiz was already submitted.")
        s.submitted = True
        per_topic: dict[str, dict] = {}
        review = []
        for q in s.questions:
            given = answers.get(q["id"])
            correct = given == q["answer"]
            t = per_topic.setdefault(q["topic"], {"correct": 0, "total": 0, "answered": 0})
            t["total"] += 1
            t["answered"] += given is not None
            t["correct"] += correct
            review.append({"id": q["id"], "topic": q["topic"], "question": q["question"], "options": q["options"],
                           "given": given, "answer": q["answer"], "correct": correct,
                           "explanation": q["explanation"]})
        for t in per_topic.values():
            t["ratio"] = t["correct"] / t["total"]
            t["level"] = s.level
        total_correct = sum(t["correct"] for t in per_topic.values())
        return {"topics": per_topic, "correct": total_correct, "total": len(s.questions), "level": s.level,
                "ratio": total_correct / len(s.questions) if s.questions else 0.0, "review": review}

    def _expire(self) -> None:
        cutoff = time.time() - SESSION_TTL_SECONDS
        for sid in [k for k, v in self.sessions.items() if v.created < cutoff]:
            del self.sessions[sid]

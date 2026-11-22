"""Personal learning roadmap from a job match.

1. Gaps = job skills with a weak quiz result (first) or with no evidence at all.
2. Each gap selects the hand-written topic that teaches it; skills without a
   topic get a generic step so nothing disappears silently.
3. Prerequisites are inserted before the topic that needs them, unless the user
   already has evidence for one of the prerequisite's skills.
4. Topics appear once (de-duplicated), in dependency order.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP_FILE = ROOT / "data" / "roadmap.json"
COURSES_FILE = ROOT / "data" / "courses.json"


@lru_cache(maxsize=1)
def load_topics(path: str = str(ROADMAP_FILE)) -> dict[str, dict]:
    topics = {t["id"]: t for t in json.loads(Path(path).read_text(encoding="utf-8"))["topics"]}
    for t in topics.values():
        for p in t["prereqs"]:
            if p not in topics:
                raise ValueError(f"topic {t['id']}: unknown prerequisite {p}")
    _check_acyclic(topics)
    return topics


def _check_acyclic(topics: dict[str, dict]) -> None:
    state: dict[str, int] = {}

    def visit(tid: str, path: list[str]) -> None:
        if state.get(tid) == 1:
            raise ValueError("prerequisite cycle: " + " -> ".join(path + [tid]))
        if state.get(tid) == 2:
            return
        state[tid] = 1
        for p in topics[tid]["prereqs"]:
            visit(p, path + [tid])
        state[tid] = 2

    for tid in topics:
        visit(tid, [])


def load_courses(path: Path = COURSES_FILE) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("courses", {})


def build_roadmap(match: dict, cv_skills: list[str] | None = None, quiz_scores: dict[str, dict] | None = None,
                  topics: dict[str, dict] | None = None, courses: dict[str, list[dict]] | None = None) -> dict:
    """`match` is the output of matching.match_job. `cv_skills` / `quiz_scores` are the user's full
    evidence, so a prerequisite the job does not mention (e.g. Docker in the CV) still counts as known."""
    from .matching import WEAK_BELOW
    from .skills import default_dictionary

    topics = topics or load_topics()
    courses = load_courses() if courses is None else courses
    skill_topic = {s: tid for tid, t in topics.items() for s in t["skills"]}
    rows = match["skills"]
    strong_topics = {t for t, q in (quiz_scores or {}).items() if q["ratio"] >= WEAK_BELOW}
    d = default_dictionary()
    evidenced = {r["skill"] for r in rows if r["status"] in ("cv_only", "cv_and_quiz", "quiz_only")}
    evidenced |= set(cv_skills or [])
    evidenced |= {s for s in d.skills if d.topic_of(s) in strong_topics}
    weak = {r["skill"] for r in rows if r["status"] == "weak_quiz"}
    evidenced -= weak

    gaps = [r for r in rows if r["status"] == "weak_quiz"] + [r for r in rows if r["status"] == "missing"]
    if not gaps:
        return {"steps": [], "message": "No gaps found for this job: every required skill has CV or quiz evidence."}

    steps: list[dict] = []
    placed: set[str] = set()

    def reason_for(r: dict) -> str:
        if r["status"] == "weak_quiz":
            q = r["quiz"]
            level = f" ({q['level']} level)" if q.get("level") else ""
            return (f"The job asks for {r['skill']}; your {r['topic_name']} quiz score{level} is "
                    f"{q['ratio']:.0%} ({q['correct']}/{q['total']}).")
        return f"The job asks for {r['skill']}; it was not found in your CV or quiz results."

    def known(tid: str) -> bool:
        return any(s in evidenced for s in topics[tid]["skills"])

    def add(tid: str, reason: str, for_skills: list[str], kind: str) -> None:
        if tid in placed:  # merge a repeated topic instead of listing it twice
            step = next(x for x in steps if x["id"] == tid)
            for s in for_skills:
                if s not in step["for_skills"]:
                    step["for_skills"].append(s)
            if kind == "gap" and step["kind"] == "prerequisite":  # also a direct gap: say why
                step["kind"], step["reason"] = "gap", reason
            return
        for p in topics[tid]["prereqs"]:
            if not known(p):
                add(p, f"Prerequisite for {topics[tid]['title']}.", [], "prerequisite")
        placed.add(tid)
        t = topics[tid]
        steps.append({"id": tid, "title": t["title"], "kind": kind, "reason": reason, "goal": t["goal"],
                      "for_skills": list(for_skills), "courses": courses.get(tid, [])})

    for r in gaps:
        tid = skill_topic.get(r["skill"])
        if tid is None:
            gid = f"generic:{r['skill']}"
            if gid not in placed:
                placed.add(gid)
                steps.append({"id": gid, "title": f"Learn {r['skill']}", "kind": "gap", "reason": reason_for(r),
                              "goal": f"Complete an introductory {r['skill']} tutorial and build one small project.",
                              "for_skills": [r["skill"]], "courses": []})
            continue
        add(tid, reason_for(r), [r["skill"]], "gap")
    for i, s in enumerate(steps, 1):
        s["order"] = i
    return {"steps": steps, "message": None}

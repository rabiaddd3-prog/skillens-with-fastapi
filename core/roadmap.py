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
                  topics: dict[str, dict] | None = None, courses: dict[str, list[dict]] | None = None,
                  lang: str = "en") -> dict:
    """`match` is the output of matching.match_job. `cv_skills` / `quiz_scores` are the user's full
    evidence, so a prerequisite the job does not mention (e.g. Docker in the CV) still counts as known."""
    from .i18n import msg, norm_lang
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
        return {"steps": [], "message": msg("road.no_gaps", lang)}

    steps: list[dict] = []
    placed: set[str] = set()

    def reason_for(r: dict) -> str:
        if r["status"] == "weak_quiz":
            q = r["quiz"]
            level = msg("road.level", lang, level=q["level"]) if q.get("level") else ""
            return msg("road.weak", lang, skill=r["skill"], topic=r["topic_name"], level=level,
                       pct=f"{q['ratio']:.0%}", pct_num=round(q["ratio"] * 100),
                       correct=q["correct"], total=q["total"])
        return msg("road.missing", lang, skill=r["skill"])

    def text(tid: str, field: str) -> str:
        """Topic title/goal in the requested language (title_tr / goal_tr in roadmap.json), English fallback."""
        t = topics[tid]
        return t.get(f"{field}_{norm_lang(lang)}", t[field]) if norm_lang(lang) != "en" else t[field]

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
                add(p, msg("road.prereq", lang, title=text(tid, "title")), [], "prerequisite")
        placed.add(tid)
        steps.append({"id": tid, "title": text(tid, "title"), "kind": kind, "reason": reason,
                      "goal": text(tid, "goal"), "for_skills": list(for_skills), "courses": courses.get(tid, [])})

    for r in gaps:
        tid = skill_topic.get(r["skill"])
        if tid is None:
            gid = f"generic:{r['skill']}"
            if gid not in placed:
                placed.add(gid)
                steps.append({"id": gid, "title": msg("road.generic_title", lang, skill=r["skill"]), "kind": "gap",
                              "reason": reason_for(r),
                              "goal": msg("road.generic_goal", lang, skill=r["skill"]),
                              "for_skills": [r["skill"]], "courses": []})
            continue
        add(tid, reason_for(r), [r["skill"]], "gap")
    ids = {s["id"] for s in steps}
    for i, s in enumerate(steps, 1):
        s["order"] = i
        # Prerequisite steps that are part of this plan (known prerequisites were skipped).
        s["prereqs"] = [p for p in topics.get(s["id"], {}).get("prereqs", []) if p in ids]
    return {"steps": steps, "message": None}

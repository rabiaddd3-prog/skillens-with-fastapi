"""Explainable job matching from CV evidence and quiz evidence (kept separate).

Scores, all in [0, 1]:
  cv_coverage      = job skills found in the confirmed CV / all job skills
  quiz_performance = mean quiz ratio over the job's quiz topics that were measured
  quiz_coverage    = measured job quiz topics / all job quiz topics
  combined         = W_CV * cv_coverage + W_QUIZ * quiz_performance
                     if no job topic was measured: combined = cv_coverage (stated in `notes`)
If the job has no recognised skills every score is None ("could not be calculated").
"""
from __future__ import annotations

from .skills import SkillDictionary, default_dictionary

W_CV, W_QUIZ = 0.5, 0.5
WEAK_BELOW = 0.6  # quiz ratio below this counts as weak evidence


def skill_status(in_cv: bool, quiz: dict | None) -> str:
    if quiz is not None and quiz["ratio"] < WEAK_BELOW:
        return "weak_quiz"
    if in_cv and quiz is not None:
        return "cv_and_quiz"
    if quiz is not None:
        return "quiz_only"
    if in_cv:
        return "cv_only"
    return "missing"


def match_job(job_skills: list[str], cv_skills: list[str], quiz_scores: dict[str, dict],
              dictionary: SkillDictionary | None = None) -> dict:
    """quiz_scores: {topic: {"correct": int, "total": int, "ratio": float}} for measured topics only."""
    d = dictionary or default_dictionary()
    cv = set(cv_skills)
    rows = []
    for skill in dict.fromkeys(job_skills):  # de-duplicate, keep order
        topic = d.topic_of(skill)
        quiz = quiz_scores.get(topic) if topic else None
        rows.append({
            "skill": skill,
            "topic": topic,
            "topic_name": d.topics.get(topic) if topic else None,
            "in_cv": skill in cv,
            "quiz": quiz,
            "quiz_state": "no_quiz_for_skill" if topic is None else ("measured" if quiz else "not_evaluated"),
            "status": skill_status(skill in cv, quiz),
        })

    notes = []
    if not rows:
        return {"skills": [], "scores": {"cv_coverage": None, "quiz_performance": None, "quiz_coverage": None,
                                         "combined": None},
                "notes": ["No skills were extracted from this job, so the score could not be calculated."],
                "weights": {"cv": W_CV, "quiz": W_QUIZ}}

    cv_cov = sum(r["in_cv"] for r in rows) / len(rows)
    job_topics = sorted({r["topic"] for r in rows if r["topic"]})
    measured = [t for t in job_topics if t in quiz_scores]
    quiz_perf = sum(quiz_scores[t]["ratio"] for t in measured) / len(measured) if measured else None
    quiz_cov = len(measured) / len(job_topics) if job_topics else None
    if quiz_perf is None:
        combined = cv_cov
        notes.append("No quiz result covers this job's topics; combined score = CV coverage only.")
    else:
        combined = W_CV * cv_cov + W_QUIZ * quiz_perf
    not_eval = [r["skill"] for r in rows if r["quiz_state"] == "not_evaluated"]
    if not_eval:
        notes.append("Not evaluated by quiz: " + ", ".join(not_eval) + ".")
    return {"skills": rows,
            "scores": {"cv_coverage": cv_cov, "quiz_performance": quiz_perf, "quiz_coverage": quiz_cov,
                       "combined": combined},
            "job_topics": job_topics, "measured_topics": measured, "notes": notes,
            "weights": {"cv": W_CV, "quiz": W_QUIZ}}


def rank_jobs(jobs: list[dict], cv_skills: list[str], quiz_scores: dict[str, dict]) -> list[dict]:
    """jobs: [{"id", "title", ..., "skills": [canonical]}]. Jobs without a score go last."""
    ranked = []
    for job in jobs:
        result = match_job(job["skills"], cv_skills, quiz_scores)
        ranked.append({**{k: v for k, v in job.items() if k != "skills"}, "match": result})
    return sorted(ranked, key=lambda j: (j["match"]["scores"]["combined"] is None,
                                         -(j["match"]["scores"]["combined"] or 0)))

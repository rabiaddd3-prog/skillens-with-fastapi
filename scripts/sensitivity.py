"""How much do the hand-set matching constants change the results?

core/matching.py has two constants chosen by hand:
  W_CV / W_QUIZ  weights of CV coverage and quiz performance in the combined score (0.5 / 0.5)
  WEAK_BELOW     quiz ratio under which a skill counts as weak evidence (0.6)

No real user data exists, so profiles are drawn at random (stated in the output):
each profile has a random subset of the dictionary skills as its CV and random quiz
ratios (multiples of 1/5, like a 5-question quiz) for a random subset of the topics.
For every profile the 25 catalog jobs are ranked with the default weights and with
each alternative; we report Kendall's tau and top-3 overlap against the default.
WEAK_BELOW only changes skill status labels (the gap list), not the score, so for it
we report how many job-skill rows change status.

Usage: python scripts/sensitivity.py --profiles 500 --seed 0
Writes results/sensitivity.json.
"""
import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import matching  # noqa: E402
from core.jobs import DEFAULT_DB, JobStore  # noqa: E402
from core.skills import default_dictionary  # noqa: E402
from core.utils import write_json  # noqa: E402


def kendall_tau(a: list, b: list) -> float:
    """Kendall's tau-a between two orderings of the same items."""
    pos = {x: i for i, x in enumerate(b)}
    n, concord, discord = len(a), 0, 0
    for i in range(n):
        for j in range(i + 1, n):
            if pos[a[i]] < pos[a[j]]:
                concord += 1
            else:
                discord += 1
    return (concord - discord) / (n * (n - 1) / 2)


def ranking(jobs, cv, quiz):
    scored = [(j["id"], matching.match_job(j["skills"], cv, quiz)["scores"]["combined"]) for j in jobs]
    # Ties broken by id so that equal scores do not count as rank changes in random order.
    return [i for i, s in sorted(scored, key=lambda x: (x[1] is None, -(x[1] or 0), x[0]))]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--profiles", type=int, default=500)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--out", default="results/sensitivity.json")
    args = p.parse_args()
    rng = random.Random(args.seed)
    d = default_dictionary()
    jobs = [{"id": j["id"], "skills": d.normalize(j["description"])} for j in JobStore(args.db).list()]
    jobs = [j for j in jobs if j["skills"]]
    skills, topics = list(d.skills), list(d.topics)

    profiles = []
    for _ in range(args.profiles):
        cv = rng.sample(skills, rng.randint(2, 15))
        quiz = {t: {"correct": (c := rng.randint(0, 5)), "total": 5, "ratio": c / 5}
                for t in rng.sample(topics, rng.randint(0, len(topics)))}
        profiles.append((cv, quiz))

    default_w = matching.W_CV
    base = [ranking(jobs, cv, quiz) for cv, quiz in profiles]
    weights = {}
    for w in (0.0, 0.25, 0.4, 0.6, 0.75, 1.0):
        matching.W_CV, matching.W_QUIZ = w, 1 - w
        taus, top1, top3 = [], [], []
        for (cv, quiz), ref in zip(profiles, base):
            r = ranking(jobs, cv, quiz)
            taus.append(kendall_tau(ref, r))
            top1.append(r[0] == ref[0])
            top3.append(len(set(r[:3]) & set(ref[:3])) / 3)
        weights[f"{w:.2f}"] = {"mean_kendall_tau": round(statistics.fmean(taus), 4),
                               "min_kendall_tau": round(min(taus), 4),
                               "top1_same": round(statistics.fmean(top1), 4),
                               "mean_top3_overlap": round(statistics.fmean(top3), 4)}
    matching.W_CV, matching.W_QUIZ = default_w, 1 - default_w

    default_weak = matching.WEAK_BELOW
    def statuses():
        return [row["status"] for cv, quiz in profiles for j in jobs
                for row in matching.match_job(j["skills"], cv, quiz)["skills"]]
    ref = statuses()
    weak = {}
    for t in (0.4, 0.5, 0.7, 0.8):
        matching.WEAK_BELOW = t
        cur = statuses()
        weak[f"{t:.2f}"] = {"rows_changed": sum(a != b for a, b in zip(ref, cur)),
                            "share_changed": round(sum(a != b for a, b in zip(ref, cur)) / len(ref), 4)}
    matching.WEAK_BELOW = default_weak

    out = {"note": "Random synthetic profiles, not real users.", "profiles": args.profiles, "seed": args.seed,
           "jobs": len(jobs), "default": {"W_CV": default_w, "WEAK_BELOW": default_weak},
           "weights_vs_default": weights, "weak_threshold_vs_default": weak, "job_skill_rows": len(ref)}
    write_json(Path(args.out), out)
    import json
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

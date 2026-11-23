"""Human-labelled check of the job ranking (the "gold set").

Step 1 - make the labelling sheet (blind: it does NOT show the system's scores):
    python scripts/gold_match.py template --profiles docs/gold_match/profiles.json
  -> docs/gold_match/labels.csv with one row per (profile, job). Read each job ad and
     write in `relevance` how well the job fits that profile, by your own judgement:
       0 = does not fit, 1 = partly fits, 2 = fits well.
Step 2 - score the system against your labels:
    python scripts/gold_match.py score --profiles docs/gold_match/profiles.json
  -> results/gold_match.json: NDCG@5, precision@3 (relevance 2 counts as relevant),
     and Spearman correlation between the system score and your label, for
     CV-only, combined (CV + quiz) and a random-order baseline.

profiles.json: [{"id": "p1", "cv_skills": ["Python", ...], "quiz": {"python": 0.8, "sql": 0.4}}]
(quiz values are ratios 0..1 per topic; leave out topics that were not taken).
Job skills are the app's (model + dictionary, plus the Sentence-BERT fallback if available).
"""
import argparse
import csv
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.jobs import DEFAULT_DB, JobStore  # noqa: E402
from core.matching import match_job  # noqa: E402
from core.utils import write_json  # noqa: E402

LABELS = Path("docs/gold_match/labels.csv")


def job_skills(jobs, kind="distilbert"):
    """Canonical skills per job as the app computes them (cached extraction if present)."""
    from core.embed_normalize import load_default
    from core.extractor import SkillExtractor
    from core.utils import pick_device

    device = pick_device("auto")
    ex = SkillExtractor.from_checkpoint(f"checkpoints/{kind}", kind, device)
    ex.embedder = load_default(device=str(device))
    return {j["id"]: ex.extract(j["description"])["skills"] for j in jobs}


def ndcg(ranked_rel: list[int], k: int) -> float | None:
    ideal = sorted(ranked_rel, reverse=True)
    dcg = lambda rel: sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rel[:k]))  # noqa: E731
    return dcg(ranked_rel) / dcg(ideal) if dcg(ideal) > 0 else None


def spearman(x: list[float], y: list[float]) -> float | None:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for t in range(i, j + 1):
                r[order[t]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    if len(set(rx)) < 2 or len(set(ry)) < 2:
        return None
    return statistics.correlation(rx, ry)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["template", "score"])
    p.add_argument("--profiles", default="docs/gold_match/profiles.json")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--labels", default=str(LABELS))
    args = p.parse_args()
    profiles = json.loads(Path(args.profiles).read_text(encoding="utf-8"))
    jobs = JobStore(args.db).list()

    if args.mode == "template":
        path = Path(args.labels)
        if path.exists():
            sys.exit(f"{path} already exists; not overwriting your labels.")
        path.parent.mkdir(parents=True, exist_ok=True)
        rng = random.Random(0)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["profile", "job_id", "job_title", "company", "relevance"])
            for prof in profiles:
                order = list(jobs)
                rng.shuffle(order)  # random order, so the sheet does not suggest a ranking
                for j in order:
                    w.writerow([prof["id"], j["id"], j["title"], j["company"] or "", ""])
        print(f"written {path}: fill in `relevance` (0/1/2) for every row, then run `score`.")
        return

    labels: dict[tuple[str, int], int] = {}
    with open(args.labels, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["relevance"].strip() != "":
                labels[(row["profile"], int(row["job_id"]))] = int(row["relevance"])
    if not labels:
        sys.exit("no labels filled in yet")
    skills = job_skills(jobs)
    rng = random.Random(0)
    variants = {"cv_only": [], "combined": [], "random": []}
    per_profile = []
    for prof in profiles:
        quiz = {t: {"correct": None, "total": None, "ratio": r} for t, r in prof.get("quiz", {}).items()}
        rows = []
        for j in jobs:
            if (prof["id"], j["id"]) not in labels:
                continue
            m = match_job(skills[j["id"]], prof["cv_skills"], quiz)["scores"]
            rows.append({"job": j["id"], "rel": labels[(prof["id"], j["id"])],
                         "cv_only": m["cv_coverage"] or 0.0, "combined": m["combined"] or 0.0,
                         "random": rng.random()})
        if not rows:
            continue
        res = {"profile": prof["id"], "jobs_labelled": len(rows)}
        for v in variants:
            ranked = sorted(rows, key=lambda r: -r[v])
            rel = [r["rel"] for r in ranked]
            out = {"ndcg@5": ndcg(rel, 5), "precision@3": sum(r == 2 for r in rel[:3]) / 3,
                   "spearman": spearman([r[v] for r in rows], [r["rel"] for r in rows])}
            res[v] = out
            variants[v].append(out)
        per_profile.append(res)

    def mean(v, k):
        vals = [x[k] for x in variants[v] if x[k] is not None]
        return round(statistics.fmean(vals), 4) if vals else None

    summary = {v: {k: mean(v, k) for k in ("ndcg@5", "precision@3", "spearman")} for v in variants}
    write_json(Path("results/gold_match.json"), {"labels": len(labels), "profiles": len(per_profile),
                                                 "summary": summary, "per_profile": per_profile})
    print(json.dumps(summary, indent=2))
    print("written results/gold_match.json")


if __name__ == "__main__":
    main()

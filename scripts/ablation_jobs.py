"""Ablation on the job catalog: what does the model add over the skill dictionary?

For every job in the SQLite catalog three canonical skill sets are built:
  dictionary  - the dictionary alone on the raw job text (no model)
  model       - model spans, normalised with the dictionary (use_dictionary=False)
  app         - what the app uses: model spans + dictionary hits the model missed
It also counts model spans the dictionary could not normalise ("unmatched"):
requirements the model found that no canonical skill covers.

With --embed, unmatched spans are additionally mapped with core/embed_normalize.py
(Sentence-BERT), and the extra canonical skills this adds are reported.

Usage:
    python scripts/ablation_jobs.py --checkpoint checkpoints/distilbert --kind distilbert [--embed]
Writes results/ablation_jobs.json.
"""
import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.extractor import SkillExtractor  # noqa: E402
from core.jobs import DEFAULT_DB, JobStore  # noqa: E402
from core.skills import default_dictionary  # noqa: E402
from core.utils import pick_device, write_json  # noqa: E402


def jaccard(a: set, b: set) -> float | None:
    return len(a & b) / len(a | b) if a | b else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--checkpoint", default="checkpoints/distilbert")
    p.add_argument("--kind", default="distilbert")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--embed", action="store_true", help="also map unmatched spans with Sentence-BERT")
    p.add_argument("--out", default="results/ablation_jobs.json")
    args = p.parse_args()

    device = pick_device("auto")
    ex = SkillExtractor.from_checkpoint(args.checkpoint, args.kind, device)
    d = default_dictionary()
    embedder = None
    if args.embed:
        from core.embed_normalize import EmbeddingNormalizer

        embedder = EmbeddingNormalizer(d)

    jobs = JobStore(args.db).list()
    per_job = []
    for job in jobs:
        text = job["description"]
        dict_only = set(d.normalize(text))
        model_out = ex.extract(text, use_dictionary=False)
        app_out = ex.extract(text, use_dictionary=True)
        model_set, app_set = set(model_out["skills"]), set(app_out["skills"])
        row = {
            "id": job["id"], "title": job["title"], "source": job["source"],
            "n_dictionary": len(dict_only), "n_model": len(model_set), "n_app": len(app_set),
            "model_only": sorted(model_set - dict_only), "dictionary_only": sorted(dict_only - model_set),
            "app_minus_dictionary": sorted(app_set - dict_only),
            "jaccard_model_vs_dictionary": jaccard(model_set, dict_only),
            "n_model_requirements": len(model_out["requirements"]),
            "n_unmatched": len(model_out["unmatched"]), "unmatched": model_out["unmatched"],
        }
        if embedder is not None:
            mapped = embedder.map_many(model_out["unmatched"])
            extra = sorted({m["skill"] for m in mapped if m["skill"]} - app_set)
            row["embed_mapped"] = [m for m in mapped if m["skill"]]
            row["embed_extra_skills"] = extra
        per_job.append(row)

    def mean(key):
        vals = [r[key] for r in per_job if r[key] is not None]
        return round(statistics.fmean(vals), 4) if vals else None

    summary = {
        "jobs": len(per_job), "model": args.kind,
        "mean_skills": {"dictionary": mean("n_dictionary"), "model": mean("n_model"), "app": mean("n_app")},
        "mean_jaccard_model_vs_dictionary": mean("jaccard_model_vs_dictionary"),
        "jobs_where_app_differs_from_dictionary": sum(1 for r in per_job if r["app_minus_dictionary"]),
        "mean_model_requirements": mean("n_model_requirements"),
        "mean_unmatched": mean("n_unmatched"),
        "share_unmatched": round(sum(r["n_unmatched"] for r in per_job)
                                 / max(1, sum(r["n_model_requirements"] for r in per_job)), 4),
    }
    if embedder is not None:
        summary["embed_threshold"] = embedder.threshold
        summary["embed_model"] = embedder.model_name
        summary["mean_embed_extra_skills"] = round(statistics.fmean(len(r["embed_extra_skills"]) for r in per_job), 4)
        summary["jobs_with_embed_extra"] = sum(1 for r in per_job if r["embed_extra_skills"])
    if embedder is not None:
        # Every distinct unmatched span with its nearest alias, for a manual check of the threshold.
        # The `correct` column is left empty on purpose: it is filled in by hand (y / n).
        spans = sorted({s for r in per_job for s in r["unmatched"]})
        cands = [c for c in embedder.map_many(spans) if c["score"] is not None]
        cands.sort(key=lambda c: -c["score"])
        nearest = {}
        for c in cands:
            nearest[c["text"]] = c
        out_csv = Path(args.out).with_name("embed_candidates.csv")
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["span", "nearest_alias", "skill", "score", "correct"])
            for c in cands:
                alias, skill = c["alias"], next(sk for al, sk in embedder.labels if al == c["alias"])
                w.writerow([c["text"], alias, skill, c["score"], ""])
        summary["threshold_sweep"] = {f"{t:.2f}": sum(c["score"] >= t for c in cands)
                                      for t in (0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9)}
        summary["distinct_unmatched_spans"] = len(spans)
        summary["spans_scored"] = len(cands)
    write_json(Path(args.out), {"summary": summary, "jobs": per_job})
    print(json.dumps(summary, indent=2))
    print(f"written to {args.out}")


if __name__ == "__main__":
    main()

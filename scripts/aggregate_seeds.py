"""Mean and standard deviation of test scores and latency over all seeds.

Reads results/test_metrics.json (seed 42) and results/seeds/s*/test_metrics.json.
Writes results/seed_summary.json and docs/report/tables/seed_scores.tex.

Usage: python scripts/aggregate_seeds.py
BiLSTM-CRF runs (results/crf, results/seeds/s*/crf): python scripts/aggregate_seeds.py --sub crf
  -> results/crf_seed_summary.json (its LaTeX table comes from scripts/make_extra_tables.py)
"""
import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--sub", default="", help="subfolder of each run, e.g. crf")
cli = ap.parse_args()
runs = {"42": ROOT / "results" / cli.sub / "test_metrics.json"}
for d in sorted((ROOT / "results" / "seeds").glob("s*")):
    if (d / cli.sub / "test_metrics.json").exists():
        runs[d.name[1:]] = d / cli.sub / "test_metrics.json"
data = {seed: json.loads(p.read_text(encoding="utf-8"))["models"] for seed, p in runs.items()}
models = list(next(iter(data.values())))


def agg(values):
    return {"mean": statistics.fmean(values), "std": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": min(values), "max": max(values), "values": values}


summary = {"seeds": list(runs), "models": {}}
for m in models:
    s = {}
    for scope in ("overall", "skill", "knowledge"):
        for k in ("precision", "recall", "f1"):
            s[f"{scope}_{k}"] = agg([data[seed][m]["scores"][scope][k] for seed in runs])
    s["median_latency_ms"] = agg([data[seed][m]["latency"]["median_ms"] for seed in runs])
    s["best_val_epoch"] = [data[seed][m]["best_val_epoch"] for seed in runs]
    summary["models"][m] = s

if cli.sub:
    (ROOT / "results" / f"{cli.sub}_seed_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
else:
    (ROOT / "results" / "seed_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

rows = []
for m in models:
    s = summary["models"][m]
    cell = lambda k: f"{s[k]['mean']:.3f} $\\pm$ {s[k]['std']:.3f}"  # noqa: E731
    rows.append(f"{m} & {cell('overall_precision')} & {cell('overall_recall')} & {cell('overall_f1')} & "
                f"{cell('skill_f1')} & {cell('knowledge_f1')} \\\\")
tab = ROOT / "docs" / "report" / "tables" / "seed_scores.tex"
if not cli.sub:
    tab.write_text(
    "\\begin{tabular}{l ccc cc}\n\\hline\n"
    "Model & P & R & F1 & F1 skill & F1 knowledge \\\\\n\\hline\n" + "\n".join(rows) + "\n\\hline\n\\end{tabular}\n",
    encoding="utf-8")

print("seeds:", ", ".join(runs))
for m in models:
    s = summary["models"][m]
    print(f"{m:10s} F1 {s['overall_f1']['mean']:.4f} ± {s['overall_f1']['std']:.4f} "
          f"(skill {s['skill_f1']['mean']:.4f} ± {s['skill_f1']['std']:.4f}, "
          f"knowledge {s['knowledge_f1']['mean']:.4f} ± {s['knowledge_f1']['std']:.4f}) "
          f"| median latency {s['median_latency_ms']['mean']:.2f} ± {s['median_latency_ms']['std']:.2f} ms "
          f"| best val epochs {s['best_val_epoch']}")

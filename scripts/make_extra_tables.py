"""LaTeX tables for the extra analyses, built only from the measured result files.

Reads results/by_source.csv, results/ablation_jobs.json, results/ablation_jobs_embed.json,
results/sensitivity.json and (if present) results/crf_seed_summary.json.
Writes docs/report/tables/{by_source,ablation,sensitivity,crf_scores}.tex.

Usage: python scripts/make_extra_tables.py
"""
import csv
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES, TAB = ROOT / "results", ROOT / "docs" / "report" / "tables"


def tabular(spec: str, header: str, rows: list[str]) -> str:
    return (f"\\begin{{tabular}}{{{spec}}}\n\\hline\n{header} \\\\\n\\hline\n" + " \\\\\n".join(rows)
            + " \\\\\n\\hline\n\\end{tabular}\n")


def by_source():
    rows = list(csv.DictReader(open(RES / "by_source.csv", encoding="utf-8")))
    cell = {}
    for r in rows:
        cell.setdefault((r["model"], r["source"], r["scope"]), []).append(float(r["f1"]))
    order = [m for m in ("Dictionary", "BiLSTM", "BiLSTM-CRF", "DistilBERT") if (m, "all", "overall") in cell]
    fmt = lambda v: f"{v[0]:.3f}" if len(v) == 1 else f"{statistics.fmean(v):.3f} $\\pm$ {statistics.stdev(v):.3f}"  # noqa: E731
    out = []
    for m in order:
        out.append(" & ".join([m] + [fmt(cell[(m, src, sc)]) for src in ("tech", "house")
                                     for sc in ("overall", "skill", "knowledge")]))
    return tabular("l ccc ccc",
                   "Model & \\multicolumn{3}{c}{TECH (F1)} & \\multicolumn{3}{c}{HOUSE (F1)} \\\\\n"
                   " & overall & skill & knowledge & overall & skill & knowledge", out)


def ablation():
    a = json.loads((RES / "ablation_jobs.json").read_text(encoding="utf-8"))["summary"]
    e = json.loads((RES / "ablation_jobs_embed.json").read_text(encoding="utf-8"))["summary"]
    rows = [
        f"Mean canonical skills per job: dictionary / model / app & {a['mean_skills']['dictionary']:.2f} / "
        f"{a['mean_skills']['model']:.2f} / {a['mean_skills']['app']:.2f}",
        f"Mean Jaccard, model vs dictionary skill sets & {a['mean_jaccard_model_vs_dictionary']:.3f}",
        f"Jobs where the app's skills differ from the dictionary's & {a['jobs_where_app_differs_from_dictionary']} / {a['jobs']}",
        f"Model requirements per job (mean) & {a['mean_model_requirements']:.1f}",
        f"Share of model requirements with no canonical skill & {100 * a['share_unmatched']:.1f}\\%",
        f"Jobs gaining a skill from Sentence-BERT (threshold {e['embed_threshold']}) & {e['jobs_with_embed_extra']} / {e['jobs']}",
    ]
    return tabular("l r", "Measure (25 catalog jobs) & Value", rows)


def sensitivity():
    s = json.loads((RES / "sensitivity.json").read_text(encoding="utf-8"))
    rows = [f"{w} / {1 - float(w):.2f} & {v['mean_kendall_tau']:.3f} & {100 * v['top1_same']:.1f}\\% & "
            f"{100 * v['mean_top3_overlap']:.1f}\\%" for w, v in s["weights_vs_default"].items()]
    return tabular("c ccc", "$w_{CV}$ / $w_{quiz}$ & Kendall $\\tau$ & same top job & top-3 overlap", rows)


def crf():
    path = RES / "crf_seed_summary.json"
    if not path.exists():
        return None
    s = json.loads(path.read_text(encoding="utf-8"))["models"]
    cell = lambda m, k: f"{s[m][k]['mean']:.3f} $\\pm$ {s[m][k]['std']:.3f}"  # noqa: E731
    rows = [f"{m} & {cell(m, 'overall_precision')} & {cell(m, 'overall_recall')} & {cell(m, 'overall_f1')} & "
            f"{cell(m, 'skill_f1')} & {cell(m, 'knowledge_f1')} & {s[m]['median_latency_ms']['mean']:.2f}"
            for m in s]
    return tabular("l ccc cc c", "Model & P & R & F1 & F1 skill & F1 knowledge & ms", rows)


TAB.mkdir(parents=True, exist_ok=True)
for name, fn in (("by_source", by_source), ("ablation", ablation), ("sensitivity", sensitivity), ("crf_scores", crf)):
    tex = fn()
    if tex is None:
        print(f"skip {name} (no input yet)")
        continue
    (TAB / f"{name}.tex").write_text(tex, encoding="utf-8")
    print(f"written docs/report/tables/{name}.tex")

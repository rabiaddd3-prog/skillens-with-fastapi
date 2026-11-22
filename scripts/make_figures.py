"""Report figures and LaTeX tables, generated only from measured files.

Inputs : results/test_metrics.json, checkpoints/{bilstm,distilbert}/history.json
Outputs: docs/report/figures/*.pdf|png, docs/report/tables/*.tex

Usage: python scripts/make_figures.py
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs" / "report" / "figures"
TAB = ROOT / "docs" / "report" / "tables"
FIG.mkdir(parents=True, exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)

# Categorical slots 1-2 of the validated reference palette; ink stays neutral.
COLORS = {"BiLSTM": "#2a78d6", "DistilBERT": "#eb6834"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "legend.frameon": False, "figure.dpi": 150, "savefig.bbox": "tight",
})

metrics = json.loads((ROOT / "results" / "test_metrics.json").read_text(encoding="utf-8"))
models = metrics["models"]
names = list(models)


def save(fig, name):
    fig.savefig(FIG / f"{name}.pdf")
    fig.savefig(FIG / f"{name}.png", dpi=200)
    plt.close(fig)


# 1. Test F1 by scope ------------------------------------------------------
scopes = ["overall", "skill", "knowledge"]
fig, ax = plt.subplots(figsize=(4.8, 2.8))
width = 0.36
for i, n in enumerate(names):
    xs = [s + (i - 0.5) * width for s in range(len(scopes))]
    vals = [models[n]["scores"][s]["f1"] for s in scopes]
    bars = ax.bar(xs, vals, width * 0.94, color=COLORS[n], label=n)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.01, f"{v:.3f}", ha="center", va="bottom", fontsize=7.5, color=INK)
ax.set_xticks(range(len(scopes)), [s.capitalize() for s in scopes])
ax.set_ylabel("Entity-level F1 (test)")
ax.set_ylim(0, max(models[n]["scores"][s]["f1"] for n in names for s in scopes) * 1.2)
ax.grid(axis="x", visible=False)
ax.legend(loc="upper left", ncol=2)
save(fig, "test_f1")

# 2. Latency ---------------------------------------------------------------
fig, ax = plt.subplots(figsize=(4.8, 1.6))
for i, n in enumerate(names):
    lat = models[n]["latency"]
    ax.barh(i, lat["median_ms"], 0.5, color=COLORS[n])
    ax.plot([lat["median_ms"], lat["p90_ms"]], [i, i], color=INK2, linewidth=1)
    ax.plot([lat["p90_ms"]], [i], marker="|", markersize=10, color=INK2)
    ax.text(lat["p90_ms"] + 0.15, i, f"median {lat['median_ms']:.1f} ms · p90 {lat['p90_ms']:.1f} ms",
            va="center", fontsize=7.5, color=INK)
ax.set_yticks(range(len(names)), names)
ax.set_xlabel("ms per sentence (batch 1, incl. tokenisation)")
ax.set_xlim(0, max(models[n]["latency"]["p90_ms"] for n in names) * 1.9)
ax.grid(axis="y", visible=False)
save(fig, "latency")

# 3. Validation F1 per epoch -----------------------------------------------
fig, ax = plt.subplots(figsize=(4.8, 2.6))
for n, folder in (("BiLSTM", "bilstm"), ("DistilBERT", "distilbert")):
    hist = json.loads((ROOT / "checkpoints" / folder / "history.json").read_text(encoding="utf-8"))
    ep = [h["epoch"] for h in hist]
    f1 = [h["val_overall_f1"] for h in hist]
    ax.plot(ep, f1, color=COLORS[n], linewidth=2, label=n)
    best = max(range(len(f1)), key=f1.__getitem__)
    ax.plot([ep[best]], [f1[best]], marker="o", markersize=7, color=COLORS[n], markeredgecolor="white", markeredgewidth=1.5)
    ax.annotate(f"best: epoch {ep[best]}, {f1[best]:.3f}", (ep[best], f1[best]), textcoords="offset points",
                xytext=(0, 8), ha="center", fontsize=7.5, color=INK)
ax.set_xlabel("Epoch")
ax.set_ylabel("Validation F1 (overall)")
ax.set_ylim(0, 0.65)
ax.legend(loc="lower right")
save(fig, "val_f1_curves")

# 4. Error types -----------------------------------------------------------
types = [("boundary", "Boundary"), ("fp", "False positive"), ("fn", "False negative")]
fig, ax = plt.subplots(figsize=(4.8, 2.6))
for i, n in enumerate(names):
    e = models[n]["error_counts"]
    vals = [e.get(f"skill_{t}", 0) + e.get(f"knowledge_{t}", 0) for t, _ in types]
    xs = [k + (i - 0.5) * width for k in range(len(types))]
    bars = ax.bar(xs, vals, width * 0.94, color=COLORS[n], label=n)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 8, str(v), ha="center", va="bottom", fontsize=7.5, color=INK)
ax.set_xticks(range(len(types)), [t for _, t in types])
ax.set_ylabel("Errors on test (skill + knowledge)")
ax.set_ylim(0, ax.get_ylim()[1] * 1.08)
ax.grid(axis="x", visible=False)
ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
save(fig, "error_types")

# LaTeX tables ---------------------------------------------------------------
rows = []
for n in names:
    s = models[n]["scores"]
    rows.append(f"{n} & " + " & ".join(f"{s[k]['precision']:.3f} & {s[k]['recall']:.3f} & {s[k]['f1']:.3f}"
                                       for k in scopes) + r" \\")
(TAB / "test_scores.tex").write_text(
    "\\begin{tabular}{l ccc ccc ccc}\n\\hline\n"
    " & \\multicolumn{3}{c}{Overall} & \\multicolumn{3}{c}{Skill} & \\multicolumn{3}{c}{Knowledge} \\\\\n"
    "Model & P & R & F1 & P & R & F1 & P & R & F1 \\\\\n\\hline\n" + "\n".join(rows) + "\n\\hline\n\\end{tabular}\n",
    encoding="utf-8")

lat_rows = []
for n in names:
    m = models[n]
    lat_rows.append(f"{n} & {m['parameters'] / 1e6:.1f}M & {m['best_val_epoch']} & {m['latency']['median_ms']:.2f} & "
                    f"{m['latency']['p90_ms']:.2f} & {m['latency']['mean_ms']:.2f} \\\\")
(TAB / "efficiency.tex").write_text(
    "\\begin{tabular}{l r c r r r}\n\\hline\n"
    "Model & Params & Best val. epoch & Median ms & p90 ms & Mean ms \\\\\n\\hline\n"
    + "\n".join(lat_rows) + "\n\\hline\n\\end{tabular}\n", encoding="utf-8")

def tex(s):
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\^{}"),
                 ("•", r"\textbullet{}")):
        s = s.replace(a, b)
    return s


# Real DistilBERT error examples: first two short sentences of each error type, in file order.
errors = [json.loads(line) for line in (ROOT / "results" / "errors_distilbert.jsonl").read_text(encoding="utf-8").splitlines()]
ex_rows = []
for kind, label in (("fp", "False positive"), ("fn", "False negative"), ("boundary", "Boundary")):
    picked = [e for e in errors if e["type"] == kind and len(e["sentence"]) <= 110][:2]
    for e in picked:
        ex_rows.append(f"{label} & {e['head']} & {tex(e['gold'] or '--')} & {tex(e['pred'] or '--')} & "
                       f"\\footnotesize {tex(e['sentence'])} \\\\")
(TAB / "error_examples.tex").write_text(
    "\\begin{tabular}{l l p{2.3cm} p{2.3cm} p{5.2cm}}\n\\hline\n"
    "Error & Type & Gold span & Predicted span & Sentence \\\\\n\\hline\n" + "\n".join(ex_rows)
    + "\n\\hline\n\\end{tabular}\n", encoding="utf-8")

print("figures:", sorted(p.name for p in FIG.glob("*.pdf")))
print("tables :", sorted(p.name for p in TAB.glob("*.tex")))

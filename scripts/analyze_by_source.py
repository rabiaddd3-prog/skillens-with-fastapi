"""Two extra analyses on the SkillSpan TEST split, from saved predictions (no retraining):

1. Per-source scores: entity-level P/R/F1 separately for TECH and HOUSE job ads,
   for every model and seed whose predictions are saved under results/.
2. Dictionary-only baseline: the app's skill dictionary (data/skills.json) used as a
   tagger. Every dictionary match becomes a Knowledge span (tools, languages and
   technologies are Knowledge in SkillSpan); it never predicts Skill spans.

Usage:
    python scripts/analyze_by_source.py --results results
Writes results/by_source.csv and results/dictionary_baseline.json.
"""
import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.data import load_splits  # noqa: E402
from core.labels import HEADS  # noqa: E402
from core.metrics import entity_scores  # noqa: E402
from core.skills import default_dictionary  # noqa: E402
from core.utils import write_json  # noqa: E402


def dictionary_tags(tokens: list[str], dictionary) -> list[str]:
    """BIO tags from dictionary matches on the space-joined tokens (match must cover whole tokens)."""
    starts, ends, pos = [], [], 0
    for t in tokens:
        starts.append(pos)
        ends.append(pos + len(t))
        pos += len(t) + 1
    text = " ".join(tokens)
    tags = ["O"] * len(tokens)
    for m in dictionary.find(text):
        idx = [i for i in range(len(tokens)) if starts[i] < m.end and m.start < ends[i]]
        if not idx or starts[idx[0]] != m.start or ends[idx[-1]] != m.end:
            continue  # match inside a token, e.g. "Python-based"; SkillSpan spans are whole tokens
        if any(tags[i] != "O" for i in idx):
            continue
        tags[idx[0]] = "B"
        for i in idx[1:]:
            tags[i] = "I"
    return tags


def subset(tags_by_head: dict, ids: list[int]) -> dict:
    return {h: [tags_by_head[h][i] for i in ids] for h in HEADS}


def load_preds(path: Path) -> dict:
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    rows.sort(key=lambda r: r["sentence_id"])
    return {h: [r[h] for r in rows] for h in HEADS}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results", default="results")
    args = p.parse_args()
    res = Path(args.results)

    test = load_splits()["test"]
    gold = {h: test[f"tags_{h}"] for h in HEADS}
    sources = test["source"]
    groups = {"all": list(range(len(sources)))}
    for src in sorted(set(sources)):
        groups[src] = [i for i, s in enumerate(sources) if s == src]

    runs = {"42": res}
    for d in sorted((res / "seeds").glob("s*")):
        runs[d.name[1:]] = d

    rows = []
    per_model: dict[tuple, list[float]] = {}
    for seed, folder in runs.items():
        for model in ("BiLSTM", "BiLSTM-CRF", "DistilBERT"):
            # The BiLSTM-CRF variant was evaluated separately into <folder>/crf (scripts/evaluate.py --bilstm-crf).
            f = (folder / "crf" if model == "BiLSTM-CRF" else folder) / f"predictions_{model.lower()}.jsonl"
            if not f.exists():
                continue
            preds = load_preds(f)
            for group, ids in groups.items():
                sc = entity_scores(subset(gold, ids), subset(preds, ids))
                for scope in ("overall", *HEADS):
                    s = sc[scope]
                    rows.append({"model": model, "seed": seed, "source": group, "scope": scope,
                                 "precision": round(s["precision"], 4), "recall": round(s["recall"], 4),
                                 "f1": round(s["f1"], 4), "tp": s["tp"], "n_pred": s["n_pred"],
                                 "n_gold": s["n_gold"]})
                    per_model.setdefault((model, group, scope), []).append(s["f1"])

    dictionary = default_dictionary()
    dict_pred = {"skill": [["O"] * len(t) for t in test["tokens"]],
                 "knowledge": [dictionary_tags(t, dictionary) for t in test["tokens"]]}
    baseline = {}
    for group, ids in groups.items():
        sc = entity_scores(subset(gold, ids), subset(dict_pred, ids))
        baseline[group] = sc
        for scope in ("overall", *HEADS):
            s = sc[scope]
            rows.append({"model": "Dictionary", "seed": "-", "source": group, "scope": scope,
                         "precision": round(s["precision"], 4), "recall": round(s["recall"], 4),
                         "f1": round(s["f1"], 4), "tp": s["tp"], "n_pred": s["n_pred"], "n_gold": s["n_gold"]})

    with open(res / "by_source.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    write_json(res / "dictionary_baseline.json", {
        "description": "data/skills.json matches tagged as Knowledge spans; no Skill spans predicted.",
        "dictionary_version": dictionary.version, "n_dictionary_skills": len(dictionary.skills),
        "sentences": {g: len(ids) for g, ids in groups.items()}, "scores": baseline})

    print(f"{'model':11s} {'source':6s} {'scope':10s} F1 mean ± std (n seeds)")
    for (model, group, scope), v in sorted(per_model.items()):
        sd = statistics.stdev(v) if len(v) > 1 else 0.0
        print(f"{model:11s} {group:6s} {scope:10s} {statistics.fmean(v):.4f} ± {sd:.4f} ({len(v)})")
    for group, sc in baseline.items():
        print(f"{'Dictionary':11s} {group:6s} knowledge  P {sc['knowledge']['precision']:.4f} "
              f"R {sc['knowledge']['recall']:.4f} F1 {sc['knowledge']['f1']:.4f} | overall F1 {sc['overall']['f1']:.4f}")
    print(f"written to {res}")


if __name__ == "__main__":
    main()

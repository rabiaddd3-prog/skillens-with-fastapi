"""Final comparison of both checkpoints on the SkillSpan TEST split, under identical conditions.

Accuracy: entity-level P/R/F1 (exact boundaries + type), overall and per head.
Latency : end-to-end per-sentence time (tokens in -> word tags out, so it INCLUDES
          vocabulary lookup / subword tokenization and decoding), batch size 1,
          same sentences, same device, after warm-up. Median, p90 and mean reported.
Errors  : every FP / FN / boundary error saved as JSONL, plus counts.

Usage:
    python scripts/evaluate.py --bilstm checkpoints/bilstm --distilbert checkpoints/distilbert --out results
"""
import argparse
import csv
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402

from core import bilstm, distilbert  # noqa: E402
from core.data import load_splits  # noqa: E402
from core.errors import classify_errors  # noqa: E402
from core.labels import HEADS  # noqa: E402
from core.metrics import entity_scores  # noqa: E402
from core.utils import pick_device, run_info, set_seed, write_json  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--bilstm", default="checkpoints/bilstm")
p.add_argument("--distilbert", default="checkpoints/distilbert")
p.add_argument("--out", default="results")
p.add_argument("--device", default="auto")
p.add_argument("--latency-sentences", type=int, default=500)
p.add_argument("--warmup", type=int, default=20)
p.add_argument("--seed", type=int, default=42)
args = p.parse_args()

set_seed(args.seed)
device = pick_device(args.device)
out = Path(args.out)
test = load_splits()["test"]
sentences = test["tokens"]
gold = {h: test[f"tags_{h}"] for h in HEADS}

lstm_model, vocab, lstm_extra = bilstm.load_checkpoint(args.bilstm, device)
bert_model, tokenizer, bert_meta = distilbert.load_checkpoint(args.distilbert, device)
models = {
    "BiLSTM": (lambda sents, bs: bilstm.predict_tags(lstm_model, vocab, sents, batch_size=bs, device=device),
               sum(x.numel() for x in lstm_model.parameters()), lstm_extra.get("epoch")),
    "DistilBERT": (lambda sents, bs: distilbert.predict_tags(bert_model, tokenizer, sents, batch_size=bs,
                                                             max_length=bert_meta["max_length"], device=device),
                   sum(x.numel() for x in bert_model.parameters()), bert_meta["extra"].get("epoch")),
}


def sync():
    if device.type == "cuda":
        torch.cuda.synchronize()


latency_set = [s for s in sentences if s][: args.latency_sentences]
results, rows = {}, []
for name, (predict, n_params, best_epoch) in models.items():
    preds = predict(sentences, 32)
    scores = entity_scores(gold, preds)
    errors = classify_errors(sentences, gold, preds)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"errors_{name.lower()}.jsonl", "w", encoding="utf-8") as f:
        for e in errors:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(out / f"predictions_{name.lower()}.jsonl", "w", encoding="utf-8") as f:
        for i, toks in enumerate(sentences):
            f.write(json.dumps({"sentence_id": i, "tokens": toks, **{h: preds[h][i] for h in HEADS}}) + "\n")

    for s in latency_set[: args.warmup]:
        predict([s], 1)
    times = []
    for s in latency_set:
        sync()
        t0 = time.perf_counter()
        predict([s], 1)
        sync()
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    latency = {"median_ms": statistics.median(times), "p90_ms": times[int(0.9 * (len(times) - 1))],
               "mean_ms": statistics.fmean(times), "n_sentences": len(times), "batch_size": 1,
               "warmup_sentences": args.warmup, "includes_preprocessing": True}

    error_counts = Counter(f"{e['head']}_{e['type']}" for e in errors)
    results[name] = {"best_val_epoch": best_epoch, "parameters": n_params, "scores": scores,
                     "latency": latency, "error_counts": dict(sorted(error_counts.items()))}
    for scope in ("overall", *HEADS):
        s = scores[scope]
        rows.append({"model": name, "scope": scope, "precision": round(s["precision"], 4),
                     "recall": round(s["recall"], 4), "f1": round(s["f1"], 4), "tp": s["tp"],
                     "n_pred": s["n_pred"], "n_gold": s["n_gold"],
                     "median_latency_ms": round(latency["median_ms"], 3) if scope == "overall" else ""})
    print(f"{name:10s} F1 overall {scores['overall']['f1']:.4f} skill {scores['skill']['f1']:.4f} "
          f"knowledge {scores['knowledge']['f1']:.4f} | median latency {latency['median_ms']:.2f} ms "
          f"(p90 {latency['p90_ms']:.2f}) | errors {len(errors)}", flush=True)

write_json(out / "test_metrics.json", {"run": run_info(device, vars(args)), "test_sentences": len(sentences),
                                        "models": results})
with open(out / "comparison.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(f"written to {out}")

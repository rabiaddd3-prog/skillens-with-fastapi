"""Fine-tune DistilBERT (two heads) on SkillSpan train; keep the epoch with the best validation F1.

Training windows are capped at --max-length subwords to fit a 4 GB GPU; only
train sentences longer than that are split (validation/test max is 196 subwords,
see docs/data_notes.md). The test split is not used here.

Smoke test (checks that the code runs, NOT a result):
    python scripts/train_distilbert.py --limit-train 200 --limit-val 100 --epochs 1 --out runs/smoke_distilbert
Full run:
    python scripts/train_distilbert.py --out checkpoints/distilbert
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402
from torch.utils.data import DataLoader  # noqa: E402
from transformers import AutoTokenizer, get_linear_schedule_with_warmup  # noqa: E402

from core.data import bert_collate, bert_encode, load_splits  # noqa: E402
from core.distilbert import DEFAULT_MODEL, DistilBertTagger, predict_tags, save_checkpoint  # noqa: E402
from core.labels import HEADS  # noqa: E402
from core.metrics import entity_scores  # noqa: E402
from core.utils import pick_device, run_info, set_seed, write_json  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--out", default="checkpoints/distilbert")
p.add_argument("--model", default=DEFAULT_MODEL)
p.add_argument("--epochs", type=int, default=10)
p.add_argument("--patience", type=int, default=3, help="stop after this many epochs without val F1 gain")
p.add_argument("--batch-size", type=int, default=16)
p.add_argument("--lr", type=float, default=5e-5)
p.add_argument("--weight-decay", type=float, default=0.01)
p.add_argument("--warmup", type=float, default=0.1, help="fraction of steps for linear warm-up")
p.add_argument("--max-length", type=int, default=256)
p.add_argument("--dropout", type=float, default=0.1)
p.add_argument("--clip", type=float, default=1.0)
p.add_argument("--no-fp16", action="store_true")
p.add_argument("--seed", type=int, default=42)
p.add_argument("--device", default="auto")
p.add_argument("--limit-train", type=int, default=None, help="smoke test only")
p.add_argument("--limit-val", type=int, default=None, help="smoke test only")
args = p.parse_args()

set_seed(args.seed)
device = pick_device(args.device)
use_amp = device.type == "cuda" and not args.no_fp16
out = Path(args.out)
ds = load_splits()
train, val = ds["train"], ds["validation"]
if args.limit_train:
    train = train.select(range(min(args.limit_train, len(train))))
if args.limit_val:
    val = val.select(range(min(args.limit_val, len(val))))
is_smoke = bool(args.limit_train or args.limit_val)

tokenizer = AutoTokenizer.from_pretrained(args.model)
train_feats = [f for sid, r in enumerate(train) for f in bert_encode(r, tokenizer, args.max_length, sid)]
generator = torch.Generator().manual_seed(args.seed)
loader = DataLoader(train_feats, batch_size=args.batch_size, shuffle=True, generator=generator,
                    collate_fn=lambda b: bert_collate(b, tokenizer.pad_token_id))

model = DistilBertTagger.from_pretrained(args.model, args.dropout).to(device)
no_decay = ("bias", "LayerNorm.weight")
groups = [
    {"params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)],
     "weight_decay": args.weight_decay},
    {"params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)], "weight_decay": 0.0},
]
optim = torch.optim.AdamW(groups, lr=args.lr)
total_steps = len(loader) * args.epochs
sched = get_linear_schedule_with_warmup(optim, int(args.warmup * total_steps), total_steps)
scaler = torch.amp.GradScaler("cuda", enabled=use_amp)

info = run_info(device, vars(args))
info.update(smoke_test=is_smoke, train_sentences=len(train), train_windows=len(train_feats),
            val_sentences=len(val), fp16=use_amp, parameters=sum(p.numel() for p in model.parameters()))
write_json(out / "run_info.json", info)
print(f"device={info['device']} fp16={use_amp} train={len(train)} sentences/{len(train_feats)} windows "
      f"val={len(val)} params={info['parameters']:,}" + ("  [SMOKE TEST]" if is_smoke else ""))

gold_val = {h: val[f"tags_{h}"] for h in HEADS}
history, best_f1, best_epoch, bad_epochs = [], -1.0, 0, 0
for epoch in range(1, args.epochs + 1):
    model.train()
    t0, total, n = time.perf_counter(), 0.0, 0
    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
            loss = model(**batch)["loss"]
        optim.zero_grad()
        scaler.scale(loss).backward()
        scaler.unscale_(optim)
        torch.nn.utils.clip_grad_norm_(model.parameters(), args.clip)
        scaler.step(optim)
        scaler.update()
        sched.step()
        total, n = total + loss.item(), n + 1
    preds = predict_tags(model, tokenizer, val["tokens"], device=device)
    scores = entity_scores(gold_val, preds)
    row = {"epoch": epoch, "train_loss": total / n, "seconds": time.perf_counter() - t0,
           **{f"val_{k}_f1": v["f1"] for k, v in scores.items()}}
    history.append(row)
    improved = scores["overall"]["f1"] > best_f1
    if improved:
        best_f1, best_epoch, bad_epochs = scores["overall"]["f1"], epoch, 0
        save_checkpoint(out, model, tokenizer, max_length=512,
                        extra={"epoch": epoch, "val_scores": scores, "seed": args.seed, "base_model": args.model})
        write_json(out / "best_val_scores.json", {"epoch": epoch, **scores})
    else:
        bad_epochs += 1
    write_json(out / "history.json", history)
    print(f"epoch {epoch:2d} loss {row['train_loss']:.4f} val F1 overall {row['val_overall_f1']:.4f} "
          f"skill {row['val_skill_f1']:.4f} knowledge {row['val_knowledge_f1']:.4f} "
          f"({row['seconds']:.1f}s){'  *best' if improved else ''}", flush=True)
    if bad_epochs >= args.patience:
        print(f"early stop: no val gain for {args.patience} epochs")
        break

if device.type == "cuda":
    print(f"peak GPU memory {torch.cuda.max_memory_allocated() / 2**20:.0f} MiB")
print(f"best epoch {best_epoch}, val overall F1 {best_f1:.4f}; checkpoint in {out}")

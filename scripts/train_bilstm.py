"""Train the BiLSTM tagger on SkillSpan train; keep the epoch with the best validation F1.

The test split is never touched here; final test numbers come from the shared
evaluation script so both models are measured the same way.

Smoke test (checks that the code runs, NOT a result):
    python scripts/train_bilstm.py --limit-train 200 --limit-val 100 --epochs 2 --out runs/smoke_bilstm
Full run:
    python scripts/train_bilstm.py --out checkpoints/bilstm
With a character BiLSTM and a CRF per head (Lample et al., 2016):
    python scripts/train_bilstm.py --char-dim 25 --crf --out checkpoints/bilstm_crf
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch  # noqa: E402
from torch.utils.data import DataLoader  # noqa: E402

from core.bilstm import (BiLSTMConfig, BiLSTMTagger, build_chars, collate_with_chars, predict_tags,  # noqa: E402
                         save_checkpoint)
from core.data import Vocab, bilstm_encode, load_splits  # noqa: E402
from core.labels import HEADS  # noqa: E402
from core.metrics import entity_scores  # noqa: E402
from core.utils import pick_device, run_info, set_seed, write_json  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("--out", default="checkpoints/bilstm")
p.add_argument("--epochs", type=int, default=30)
p.add_argument("--patience", type=int, default=5, help="stop after this many epochs without val F1 gain")
p.add_argument("--batch-size", type=int, default=32)
p.add_argument("--lr", type=float, default=1e-3)
p.add_argument("--embedding-dim", type=int, default=100)
p.add_argument("--hidden-dim", type=int, default=128)
p.add_argument("--layers", type=int, default=2)
p.add_argument("--dropout", type=float, default=0.3)
p.add_argument("--min-freq", type=int, default=2)
p.add_argument("--clip", type=float, default=5.0)
p.add_argument("--char-dim", type=int, default=0, help="> 0 adds a character BiLSTM (0 = original baseline)")
p.add_argument("--char-hidden", type=int, default=25)
p.add_argument("--crf", action="store_true", help="CRF per head instead of softmax")
p.add_argument("--seed", type=int, default=42)
p.add_argument("--device", default="auto")
p.add_argument("--limit-train", type=int, default=None, help="smoke test only")
p.add_argument("--limit-val", type=int, default=None, help="smoke test only")
args = p.parse_args()

set_seed(args.seed)
device = pick_device(args.device)
out = Path(args.out)
ds = load_splits()
train, val = ds["train"], ds["validation"]
if args.limit_train:
    train = train.select(range(min(args.limit_train, len(train))))
if args.limit_val:
    val = val.select(range(min(args.limit_val, len(val))))
is_smoke = bool(args.limit_train or args.limit_val)

vocab = Vocab.build(train["tokens"], min_freq=args.min_freq)
config = BiLSTMConfig(vocab_size=len(vocab), embedding_dim=args.embedding_dim, hidden_dim=args.hidden_dim,
                      num_layers=args.layers, dropout=args.dropout, char_dim=args.char_dim,
                      char_hidden=args.char_hidden, chars=build_chars(train["tokens"]) if args.char_dim else [],
                      use_crf=args.crf)
model = BiLSTMTagger(config).to(device)
train_items = [bilstm_encode(r, vocab) for r in train]
if args.char_dim:
    for item, r in zip(train_items, train):
        item["char_ids"] = model.encode_chars(r["tokens"])
generator = torch.Generator().manual_seed(args.seed)
loader = DataLoader(train_items, batch_size=args.batch_size, shuffle=True, collate_fn=collate_with_chars,
                    generator=generator)
optim = torch.optim.Adam(model.parameters(), lr=args.lr)

info = run_info(device, vars(args))
info.update(smoke_test=is_smoke, train_sentences=len(train), val_sentences=len(val), vocab_size=len(vocab),
            parameters=sum(p.numel() for p in model.parameters()))
write_json(out / "run_info.json", info)
print(f"device={info['device']} train={len(train)} val={len(val)} vocab={len(vocab)} params={info['parameters']:,}"
      + ("  [SMOKE TEST]" if is_smoke else ""))

gold_val = {h: val[f"tags_{h}"] for h in HEADS}
history, best_f1, best_epoch, bad_epochs = [], -1.0, 0, 0
for epoch in range(1, args.epochs + 1):
    model.train()
    t0, total, n = time.perf_counter(), 0.0, 0
    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        loss = model(**batch)["loss"]
        optim.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), args.clip)
        optim.step()
        total, n = total + loss.item(), n + 1
    scores = entity_scores(gold_val, predict_tags(model, vocab, val["tokens"], device=device))
    row = {"epoch": epoch, "train_loss": total / n, "seconds": time.perf_counter() - t0,
           **{f"val_{k}_f1": v["f1"] for k, v in scores.items()}}
    history.append(row)
    improved = scores["overall"]["f1"] > best_f1
    if improved:
        best_f1, best_epoch, bad_epochs = scores["overall"]["f1"], epoch, 0
        save_checkpoint(out, model, vocab, extra={"epoch": epoch, "val_scores": scores, "seed": args.seed})
        write_json(out / "best_val_scores.json", {"epoch": epoch, **scores})
    else:
        bad_epochs += 1
    write_json(out / "history.json", history)
    print(f"epoch {epoch:2d} loss {row['train_loss']:.4f} val F1 overall {row['val_overall_f1']:.4f} "
          f"skill {row['val_skill_f1']:.4f} knowledge {row['val_knowledge_f1']:.4f} "
          f"({row['seconds']:.1f}s){'  *best' if improved else ''}")
    if bad_epochs >= args.patience:
        print(f"early stop: no val gain for {args.patience} epochs")
        break

print(f"best epoch {best_epoch}, val overall F1 {best_f1:.4f}; checkpoint in {out}")

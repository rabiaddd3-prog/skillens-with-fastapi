"""Train and evaluate both models with extra seeds, one after another (single GPU).

Seed 42 is the main run (checkpoints/bilstm, checkpoints/distilbert, results/). Extra seeds go to
checkpoints/seeds/<model>_s<seed>/ and results/seeds/s<seed>/. Afterwards run
scripts/aggregate_seeds.py.

Usage: python scripts/run_seeds.py --seeds 13 7
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("--seeds", type=int, nargs="+", default=[13, 7])
args = p.parse_args()


def run(cmd):
    print(">>", " ".join(cmd), flush=True)
    t0 = time.time()
    subprocess.run([sys.executable, "-u", *cmd], cwd=ROOT, check=True)
    print(f"<< done in {time.time() - t0:.0f}s", flush=True)


for seed in args.seeds:
    lstm = f"checkpoints/seeds/bilstm_s{seed}"
    bert = f"checkpoints/seeds/distilbert_s{seed}"
    if not (ROOT / lstm / "model.pt").exists():
        run(["scripts/train_bilstm.py", "--seed", str(seed), "--out", lstm])
    if not (ROOT / bert / "weights.pt").exists():
        run(["scripts/train_distilbert.py", "--seed", str(seed), "--out", bert])
    run(["scripts/evaluate.py", "--bilstm", lstm, "--distilbert", bert, "--out", f"results/seeds/s{seed}",
         "--seed", str(seed)])
print("all seeds finished", flush=True)

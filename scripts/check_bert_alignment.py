"""Round-trip every SkillSpan sentence through the DistilBERT encoding and back.

Gold labels are pushed through the same path model predictions will take
(subword features -> first-subword word tags -> merged windows). Any difference
from the original word tags is an alignment bug or an information loss.

Usage: python scripts/check_bert_alignment.py [--model distilbert-base-cased] [--max-length 512]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transformers import AutoTokenizer  # noqa: E402

from core.data import bert_encode, load_splits, merge_windows, subword_counts, subword_preds_to_words, tag_ids  # noqa: E402
from core.labels import HEADS  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--model", default="distilbert-base-cased")
parser.add_argument("--max-length", type=int, default=512)
args = parser.parse_args()

tok = AutoTokenizer.from_pretrained(args.model)
ds = load_splits()
for split in ds:
    multi_window = dropped_words = mismatched = max_sub = 0
    dropped_labelled = 0
    for sid, row in enumerate(ds[split]):
        counts = subword_counts(row["tokens"], tok)
        max_sub = max(max_sub, sum(counts))
        zero = [i for i, c in enumerate(counts) if c == 0]
        dropped_words += len(zero)
        dropped_labelled += sum(any(row[f"tags_{h}"][i] != "O" for h in HEADS) for i in zero)
        feats = bert_encode(row, tok, max_length=args.max_length, sentence_id=sid)
        multi_window += len(feats) > 1
        for head in HEADS:
            words = [subword_preds_to_words(f["word_ids"], f[f"labels_{head}"], f["num_words"]) for f in feats]
            if merge_windows(feats, words, len(row["tokens"])) != tag_ids(row[f"tags_{head}"]):
                mismatched += 1
    print(f"{split}: sentences={len(ds[split])} max_subwords={max_sub} split_into_windows={multi_window} "
          f"words_without_subwords={dropped_words} (labelled={dropped_labelled}) roundtrip_mismatches={mismatched}")

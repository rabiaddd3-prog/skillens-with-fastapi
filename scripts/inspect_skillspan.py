"""Print SkillSpan splits, schema, label sets and one example.

Usage: python scripts/inspect_skillspan.py
"""
from collections import Counter

from datasets import load_dataset

ds = load_dataset("jjzha/skillspan")
print(ds)
print("features:", ds["train"].features)

ex = ds["train"][0]
for key, value in ex.items():
    shown = value[:25] if isinstance(value, list) else value
    print(f"{key} -> {shown}")

for split in ds:
    for col in ds[split].column_names:
        first = ds[split][0][col]
        if isinstance(first, list) and first and isinstance(first[0], str) and col.startswith("tags"):
            counts = Counter(tag for row in ds[split][col] for tag in row)
            print(split, col, dict(counts))

# Integrity checks: equal lengths, source mix, and token-level overlap of the two label layers.
for split in ds:
    rows = ds[split]
    bad_len = sum(
        len(t) != len(s) or len(t) != len(k)
        for t, s, k in zip(rows["tokens"], rows["tags_skill"], rows["tags_knowledge"])
    )
    overlap_tokens = sum(
        a != "O" and b != "O"
        for s, k in zip(rows["tags_skill"], rows["tags_knowledge"])
        for a, b in zip(s, k)
    )
    overlap_sents = sum(
        any(a != "O" and b != "O" for a, b in zip(s, k))
        for s, k in zip(rows["tags_skill"], rows["tags_knowledge"])
    )
    lengths = sorted(len(t) for t in rows["tokens"])
    print(
        f"{split}: length_mismatch={bad_len} overlap_tokens={overlap_tokens} "
        f"overlap_sentences={overlap_sents} sources={dict(Counter(rows['source']))} "
        f"max_len={lengths[-1]} p99_len={lengths[int(len(lengths) * 0.99)]}"
    )

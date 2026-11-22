"""SkillSpan loading and model-specific encoding.

Both models predict word-level BIO tags for two heads (Skill, Knowledge). This
module turns SkillSpan rows into tensors for each model and turns DistilBERT
subword predictions back into word-level tags, so evaluation is identical.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import torch

from .labels import HEADS, IGNORE_INDEX, LABEL2ID

DATASET_NAME = "jjzha/skillspan"
PAD, UNK = "<pad>", "<unk>"


def load_splits():
    """Return the official train/validation/test DatasetDict."""
    from datasets import load_dataset

    return load_dataset(DATASET_NAME)


def tag_ids(tags: list[str]) -> list[int]:
    return [LABEL2ID[t] for t in tags]


# ---------------------------------------------------------------- BiLSTM

@dataclass
class Vocab:
    """Word vocabulary built from the train split only. Index 0 = pad, 1 = unk."""

    itos: list[str] = field(default_factory=lambda: [PAD, UNK])
    lowercase: bool = True

    def __post_init__(self) -> None:
        self.stoi = {w: i for i, w in enumerate(self.itos)}

    @classmethod
    def build(cls, sentences: Iterable[list[str]], min_freq: int = 2, lowercase: bool = True) -> "Vocab":
        counts = Counter(w.lower() if lowercase else w for sent in sentences for w in sent)
        words = sorted(w for w, c in counts.items() if c >= min_freq)
        return cls(itos=[PAD, UNK, *words], lowercase=lowercase)

    def __len__(self) -> int:
        return len(self.itos)

    def encode(self, tokens: list[str]) -> list[int]:
        unk = self.stoi[UNK]
        return [self.stoi.get(t.lower() if self.lowercase else t, unk) for t in tokens]

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({"itos": self.itos, "lowercase": self.lowercase}), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Vocab":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(itos=data["itos"], lowercase=data["lowercase"])


def bilstm_encode(row: dict, vocab: Vocab) -> dict:
    """One SkillSpan row -> word ids and one label id list per head."""
    out = {"input_ids": vocab.encode(row["tokens"])}
    for head in HEADS:
        out[f"labels_{head}"] = tag_ids(row[f"tags_{head}"])
    return out


def bilstm_collate(batch: list[dict]) -> dict[str, torch.Tensor]:
    """Right-pad a batch. Padding gets id 0 and label IGNORE_INDEX; `mask` marks real words."""
    max_len = max(len(b["input_ids"]) for b in batch)
    out = {"input_ids": torch.zeros(len(batch), max_len, dtype=torch.long)}
    out["mask"] = torch.zeros(len(batch), max_len, dtype=torch.bool)
    has_labels = f"labels_{HEADS[0]}" in batch[0]  # absent at inference time
    if has_labels:
        for head in HEADS:
            out[f"labels_{head}"] = torch.full((len(batch), max_len), IGNORE_INDEX, dtype=torch.long)
    for i, b in enumerate(batch):
        n = len(b["input_ids"])
        out["input_ids"][i, :n] = torch.tensor(b["input_ids"])
        out["mask"][i, :n] = True
        if has_labels:
            for head in HEADS:
                out[f"labels_{head}"][i, :n] = torch.tensor(b[f"labels_{head}"])
    return out


# ---------------------------------------------------------------- DistilBERT

def word_chunks(subword_counts: list[int], max_subwords: int) -> list[tuple[int, int]]:
    """Split a sentence into consecutive word windows [start, end) whose subword
    totals fit in `max_subwords`. Windows do not overlap, so every word keeps its
    original index via the window start offset. A single word longer than the
    limit gets its own window and is truncated by the tokenizer.
    """
    chunks: list[tuple[int, int]] = []
    start, used = 0, 0
    for i, n in enumerate(subword_counts):
        if used + n > max_subwords and i > start:
            chunks.append((start, i))
            start, used = i, 0
        used += n
    if start < len(subword_counts) or not chunks:
        chunks.append((start, len(subword_counts)))
    return chunks


def subword_counts(tokens: list[str], tokenizer) -> list[int]:
    enc = tokenizer(tokens, is_split_into_words=True, add_special_tokens=False)
    counts = [0] * len(tokens)
    for wid in enc.word_ids():
        if wid is not None:
            counts[wid] += 1
    return counts


def align_labels(word_ids: list[int | None], word_label_ids: list[int]) -> list[int]:
    """Label the first subword of each word; other subwords and special tokens get IGNORE_INDEX."""
    labels, previous = [], None
    for wid in word_ids:
        if wid is None or wid == previous:
            labels.append(IGNORE_INDEX)
        else:
            labels.append(word_label_ids[wid])
        previous = wid
    return labels


def bert_encode(row: dict, tokenizer, max_length: int = 512, sentence_id: int | None = None) -> list[dict]:
    """One SkillSpan row -> one feature per word window (usually exactly one).

    Each feature keeps `word_offset` and `word_ids` so predictions can be mapped
    back to word positions in the original sentence.
    """
    tokens = row["tokens"]
    windows = word_chunks(subword_counts(tokens, tokenizer), max_length - 2)  # room for [CLS] and [SEP]
    features = []
    for start, end in windows:
        enc = tokenizer(tokens[start:end], is_split_into_words=True, truncation=True, max_length=max_length)
        word_ids = enc.word_ids()
        feat = {
            "input_ids": enc["input_ids"],
            "attention_mask": enc["attention_mask"],
            "word_ids": word_ids,
            "word_offset": start,
            "num_words": end - start,
            "sentence_id": sentence_id,
        }
        for head in HEADS:
            if f"tags_{head}" in row:
                feat[f"labels_{head}"] = align_labels(word_ids, tag_ids(row[f"tags_{head}"][start:end]))
        features.append(feat)
    return features


def bert_collate(batch: list[dict], pad_token_id: int) -> dict[str, torch.Tensor]:
    max_len = max(len(b["input_ids"]) for b in batch)
    out = {
        "input_ids": torch.full((len(batch), max_len), pad_token_id, dtype=torch.long),
        "attention_mask": torch.zeros(len(batch), max_len, dtype=torch.long),
    }
    has_labels = f"labels_{HEADS[0]}" in batch[0]
    if has_labels:
        for head in HEADS:
            out[f"labels_{head}"] = torch.full((len(batch), max_len), IGNORE_INDEX, dtype=torch.long)
    for i, b in enumerate(batch):
        n = len(b["input_ids"])
        out["input_ids"][i, :n] = torch.tensor(b["input_ids"])
        out["attention_mask"][i, :n] = torch.tensor(b["attention_mask"])
        if has_labels:
            for head in HEADS:
                out[f"labels_{head}"][i, :n] = torch.tensor(b[f"labels_{head}"])
    return out


def subword_preds_to_words(word_ids: list[int | None], pred_ids: list[int], num_words: int) -> list[int]:
    """Take each word's first-subword prediction. Words with no subwords
    (tokenizer dropped them, e.g. odd whitespace) are predicted as O."""
    out = [LABEL2ID["O"]] * num_words
    seen: set[int] = set()
    for wid, pred in zip(word_ids, pred_ids):
        if wid is not None and wid not in seen:
            out[wid] = pred
            seen.add(wid)
    return out


def merge_windows(features: list[dict], word_preds: list[list[int]], sentence_length: int) -> list[int]:
    """Place each window's word predictions back at their original offsets."""
    merged = [LABEL2ID["O"]] * sentence_length
    for feat, preds in zip(features, word_preds):
        merged[feat["word_offset"]: feat["word_offset"] + feat["num_words"]] = preds
    return merged

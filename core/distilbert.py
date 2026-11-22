"""Model B: DistilBERT encoder -> one token classifier per head.

Same task and output format as the BiLSTM: word-level O/B/I tags for Skill and
Knowledge. Subword logits are reduced to words by taking each word's first
subword, so both models are scored on identical word sequences.
"""
from __future__ import annotations

import json
from pathlib import Path

import torch
from torch import nn

from .data import bert_collate, bert_encode, merge_windows, subword_preds_to_words
from .labels import HEADS, ID2LABEL, IGNORE_INDEX, LABELS

DEFAULT_MODEL = "distilbert-base-cased"


class DistilBertTagger(nn.Module):
    def __init__(self, encoder: nn.Module, dropout: float = 0.1):
        super().__init__()
        self.encoder = encoder
        hidden = encoder.config.dim if hasattr(encoder.config, "dim") else encoder.config.hidden_size
        self.dropout = nn.Dropout(dropout)
        self.heads = nn.ModuleDict({h: nn.Linear(hidden, len(LABELS)) for h in HEADS})
        self.loss_fn = nn.CrossEntropyLoss(ignore_index=IGNORE_INDEX)

    @classmethod
    def from_pretrained(cls, name: str = DEFAULT_MODEL, dropout: float = 0.1) -> "DistilBertTagger":
        from transformers import AutoModel

        return cls(AutoModel.from_pretrained(name), dropout)

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor, **labels) -> dict:
        hidden = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        hidden = self.dropout(hidden)
        logits = {h: self.heads[h](hidden) for h in HEADS}
        result = {"logits": logits}
        if all(f"labels_{h}" in labels for h in HEADS):
            result["loss"] = sum(
                self.loss_fn(logits[h].float().reshape(-1, len(LABELS)), labels[f"labels_{h}"].reshape(-1))
                for h in HEADS
            )
        return result


def save_checkpoint(path: str | Path, model: DistilBertTagger, tokenizer, max_length: int,
                    extra: dict | None = None) -> None:
    """Encoder config, tokenizer, all weights and the label map in one directory (loads offline)."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    model.encoder.config.save_pretrained(path)
    tokenizer.save_pretrained(path)
    torch.save(model.state_dict(), path / "weights.pt")
    meta = {"labels": list(LABELS), "heads": list(HEADS), "dropout": model.dropout.p,
            "max_length": max_length, "extra": extra or {}}
    (path / "tagger.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def load_checkpoint(path: str | Path, device: torch.device | str = "cpu"):
    from transformers import AutoConfig, AutoModel, AutoTokenizer

    path = Path(path)
    if not (path / "weights.pt").exists() or not (path / "tagger.json").exists():
        raise FileNotFoundError(f"DistilBERT checkpoint not found in {path} (expected weights.pt and tagger.json)")
    meta = json.loads((path / "tagger.json").read_text(encoding="utf-8"))
    if meta["labels"] != list(LABELS) or meta["heads"] != list(HEADS):
        raise ValueError(f"checkpoint label map {meta['labels']}/{meta['heads']} does not match code")
    model = DistilBertTagger(AutoModel.from_config(AutoConfig.from_pretrained(path)), meta["dropout"])
    model.load_state_dict(torch.load(path / "weights.pt", map_location=device, weights_only=True))
    model.to(device).eval()
    return model, AutoTokenizer.from_pretrained(path), meta


@torch.no_grad()
def predict_tags(model: DistilBertTagger, tokenizer, sentences: list[list[str]], batch_size: int = 32,
                 max_length: int = 512, device: torch.device | str = "cpu") -> dict[str, list[list[str]]]:
    """Word-level BIO tags per head for each sentence, in input order."""
    model.eval()
    feats = []
    for sid, tokens in enumerate(sentences):
        if tokens:
            feats.extend(bert_encode({"tokens": tokens}, tokenizer, max_length=max_length, sentence_id=sid))
    word_preds: dict[str, list[list[int]]] = {h: [] for h in HEADS}
    for i in range(0, len(feats), batch_size):
        chunk = feats[i: i + batch_size]
        batch = bert_collate(chunk, tokenizer.pad_token_id)
        logits = model(batch["input_ids"].to(device), batch["attention_mask"].to(device))["logits"]
        for h in HEADS:
            ids = logits[h].argmax(-1).cpu().tolist()
            for f, row in zip(chunk, ids):
                word_preds[h].append(subword_preds_to_words(f["word_ids"], row, f["num_words"]))
    out: dict[str, list[list[str]]] = {h: [] for h in HEADS}
    by_sentence: dict[int, list[int]] = {}
    for idx, f in enumerate(feats):
        by_sentence.setdefault(f["sentence_id"], []).append(idx)
    for sid, tokens in enumerate(sentences):
        idxs = by_sentence.get(sid, [])
        for h in HEADS:
            merged = merge_windows([feats[j] for j in idxs], [word_preds[h][j] for j in idxs], len(tokens))
            out[h].append([ID2LABEL[t] for t in merged])
    return out

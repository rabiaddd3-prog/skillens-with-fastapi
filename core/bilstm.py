"""Model A: embedding -> bidirectional LSTM -> one token classifier per head.

The encoder is shared; the Skill and Knowledge heads each predict O/B/I for
every word, so a word can be inside a Skill span and a Knowledge span at once.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

from .data import Vocab, bilstm_collate
from .labels import HEADS, ID2LABEL, IGNORE_INDEX, LABELS


@dataclass
class BiLSTMConfig:
    vocab_size: int
    embedding_dim: int = 100
    hidden_dim: int = 128
    num_layers: int = 2
    dropout: float = 0.3
    num_labels: int = len(LABELS)


class BiLSTMTagger(nn.Module):
    def __init__(self, config: BiLSTMConfig):
        super().__init__()
        self.config = config
        self.embedding = nn.Embedding(config.vocab_size, config.embedding_dim, padding_idx=0)
        self.lstm = nn.LSTM(
            config.embedding_dim,
            config.hidden_dim,
            num_layers=config.num_layers,
            bidirectional=True,
            batch_first=True,
            dropout=config.dropout if config.num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(config.dropout)
        self.heads = nn.ModuleDict({h: nn.Linear(2 * config.hidden_dim, config.num_labels) for h in HEADS})
        self.loss_fn = nn.CrossEntropyLoss(ignore_index=IGNORE_INDEX)

    def forward(self, input_ids: torch.Tensor, mask: torch.Tensor, **labels) -> dict:
        lengths = mask.sum(dim=1).cpu()
        x = self.dropout(self.embedding(input_ids))
        # Packing keeps the backward LSTM from reading padding as if it were text.
        packed = pack_padded_sequence(x, lengths, batch_first=True, enforce_sorted=False)
        out, _ = self.lstm(packed)
        out, _ = pad_packed_sequence(out, batch_first=True, total_length=input_ids.size(1))
        out = self.dropout(out)
        logits = {h: self.heads[h](out) for h in HEADS}
        result = {"logits": logits}
        if all(f"labels_{h}" in labels for h in HEADS):
            result["loss"] = sum(
                self.loss_fn(logits[h].reshape(-1, self.config.num_labels), labels[f"labels_{h}"].reshape(-1))
                for h in HEADS
            )
        return result


def save_checkpoint(path: str | Path, model: BiLSTMTagger, vocab: Vocab, extra: dict | None = None) -> None:
    """Weights, config, vocabulary and label map go in one directory."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    torch.save(
        {"state_dict": model.state_dict(), "config": asdict(model.config), "labels": list(LABELS),
         "heads": list(HEADS), "extra": extra or {}},
        path / "model.pt",
    )
    vocab.save(path / "vocab.json")


def load_checkpoint(path: str | Path, device: torch.device | str = "cpu") -> tuple[BiLSTMTagger, Vocab, dict]:
    path = Path(path)
    if not (path / "model.pt").exists():
        raise FileNotFoundError(f"BiLSTM checkpoint not found in {path} (expected model.pt and vocab.json)")
    blob = torch.load(path / "model.pt", map_location=device, weights_only=False)
    if blob["labels"] != list(LABELS) or blob["heads"] != list(HEADS):
        raise ValueError(f"checkpoint label map {blob['labels']}/{blob['heads']} does not match code")
    model = BiLSTMTagger(BiLSTMConfig(**blob["config"])).to(device)
    model.load_state_dict(blob["state_dict"])
    model.eval()
    return model, Vocab.load(path / "vocab.json"), blob["extra"]


@torch.no_grad()
def predict_tags(model: BiLSTMTagger, vocab: Vocab, sentences: list[list[str]], batch_size: int = 64,
                 device: torch.device | str = "cpu") -> dict[str, list[list[str]]]:
    """Word-level BIO tags per head for each sentence, in input order."""
    model.eval()
    out: dict[str, list[list[str]]] = {h: [] for h in HEADS}
    for i in range(0, len(sentences), batch_size):
        chunk = sentences[i: i + batch_size]
        # Empty sentences cannot be packed; give them a placeholder and drop the prediction.
        batch = bilstm_collate([{"input_ids": vocab.encode(s) or [0]} for s in chunk])
        logits = model(batch["input_ids"].to(device), batch["mask"].to(device))["logits"]
        for h in HEADS:
            ids = logits[h].argmax(-1).cpu().tolist()
            out[h].extend([ID2LABEL[t] for t in row[: len(s)]] for row, s in zip(ids, chunk))
    return out

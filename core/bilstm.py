"""Model A: embedding -> bidirectional LSTM -> one tagger per head.

The encoder is shared; the Skill and Knowledge heads each predict O/B/I for
every word, so a word can be inside a Skill span and a Knowledge span at once.

Two optional parts follow Lample et al. (2016) and are off by default, so the
original baseline checkpoints still load unchanged:
  char_dim > 0 : a character BiLSTM per word; its final states are concatenated
                 to the word embedding (gives casing, affixes and unknown words).
  use_crf      : a linear-chain CRF per head instead of independent softmax
                 decisions; trained with the sentence log-likelihood, decoded
                 with Viterbi.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import torch
from torch import nn
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

from .data import Vocab, bilstm_collate
from .labels import HEADS, ID2LABEL, IGNORE_INDEX, LABELS

MAX_WORD_CHARS = 20


@dataclass
class BiLSTMConfig:
    vocab_size: int
    embedding_dim: int = 100
    hidden_dim: int = 128
    num_layers: int = 2
    dropout: float = 0.3
    num_labels: int = len(LABELS)
    char_dim: int = 0          # 0 = no character encoder (the original baseline)
    char_hidden: int = 25
    chars: list[str] = field(default_factory=list)  # character vocabulary; index = position + 2
    use_crf: bool = False


def build_chars(sentences: Iterable[list[str]], min_freq: int = 1) -> list[str]:
    """Character vocabulary from the train split (index 0 = pad, 1 = unknown)."""
    counts = Counter(c for sent in sentences for w in sent for c in w)
    return sorted(c for c, n in counts.items() if n >= min_freq)


class CRF(nn.Module):
    """Linear-chain CRF over the label set of one head. Masks are right-padded."""

    def __init__(self, num_labels: int):
        super().__init__()
        self.start = nn.Parameter(torch.zeros(num_labels))
        self.end = nn.Parameter(torch.zeros(num_labels))
        self.trans = nn.Parameter(torch.zeros(num_labels, num_labels))  # trans[i, j]: label i -> label j

    def nll(self, em: torch.Tensor, tags: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        """Mean negative log-likelihood of the gold sequences."""
        tags = tags.masked_fill(~mask, 0)
        b = torch.arange(em.size(0), device=em.device)
        score = self.start[tags[:, 0]] + em[b, 0, tags[:, 0]]
        alpha = self.start + em[:, 0]
        for t in range(1, em.size(1)):
            m = mask[:, t]
            score = score + (self.trans[tags[:, t - 1], tags[:, t]] + em[b, t, tags[:, t]]) * m
            nxt = torch.logsumexp(alpha.unsqueeze(2) + self.trans + em[:, t].unsqueeze(1), dim=1)
            alpha = torch.where(m.unsqueeze(1), nxt, alpha)
        last = tags[b, mask.sum(1) - 1]
        score = score + self.end[last]
        log_z = torch.logsumexp(alpha + self.end, dim=1)
        return (log_z - score).mean()

    @torch.no_grad()
    def decode(self, em: torch.Tensor, mask: torch.Tensor) -> list[list[int]]:
        """Viterbi path per sentence, cut to its length."""
        score = self.start + em[:, 0]
        back = []
        for t in range(1, em.size(1)):
            total = score.unsqueeze(2) + self.trans  # [B, from, to]
            best, idx = total.max(dim=1)
            nxt = best + em[:, t]
            m = mask[:, t].unsqueeze(1)
            score = torch.where(m, nxt, score)
            back.append(torch.where(m, idx, torch.arange(em.size(2), device=em.device).expand_as(idx)))
        score = score + self.end
        lengths = mask.sum(1).tolist()
        last = score.argmax(1).tolist()
        back = [bp.tolist() for bp in back]
        paths = []
        for i, n in enumerate(lengths):
            path = [last[i]]
            for t in range(n - 2, -1, -1):
                path.append(back[t][i][path[-1]])
            paths.append(path[::-1])
        return paths


class BiLSTMTagger(nn.Module):
    def __init__(self, config: BiLSTMConfig):
        super().__init__()
        self.config = config
        self.embedding = nn.Embedding(config.vocab_size, config.embedding_dim, padding_idx=0)
        in_dim = config.embedding_dim
        if config.char_dim > 0:
            self.char_stoi = {c: i + 2 for i, c in enumerate(config.chars)}
            self.char_embedding = nn.Embedding(len(config.chars) + 2, config.char_dim, padding_idx=0)
            self.char_lstm = nn.LSTM(config.char_dim, config.char_hidden, bidirectional=True, batch_first=True)
            in_dim += 2 * config.char_hidden
        self.lstm = nn.LSTM(
            in_dim,
            config.hidden_dim,
            num_layers=config.num_layers,
            bidirectional=True,
            batch_first=True,
            dropout=config.dropout if config.num_layers > 1 else 0.0,
        )
        self.dropout = nn.Dropout(config.dropout)
        self.heads = nn.ModuleDict({h: nn.Linear(2 * config.hidden_dim, config.num_labels) for h in HEADS})
        if config.use_crf:
            self.crfs = nn.ModuleDict({h: CRF(config.num_labels) for h in HEADS})
        self.loss_fn = nn.CrossEntropyLoss(ignore_index=IGNORE_INDEX)

    def encode_chars(self, tokens: list[str]) -> list[list[int]]:
        return [[self.char_stoi.get(c, 1) for c in w[:MAX_WORD_CHARS]] or [1] for w in tokens]

    def _char_features(self, char_ids: torch.Tensor) -> torch.Tensor:
        """[B, T, C] char ids -> [B, T, 2 * char_hidden] (final forward and backward states)."""
        b, t, c = char_ids.shape
        flat = char_ids.view(b * t, c)
        lengths = (flat != 0).sum(1).clamp(min=1).cpu()
        x = self.dropout(self.char_embedding(flat))
        packed = pack_padded_sequence(x, lengths, batch_first=True, enforce_sorted=False)
        _, (h, _) = self.char_lstm(packed)
        return torch.cat([h[0], h[1]], dim=-1).view(b, t, -1)

    def forward(self, input_ids: torch.Tensor, mask: torch.Tensor, char_ids: torch.Tensor | None = None,
                **labels) -> dict:
        lengths = mask.sum(dim=1).cpu()
        x = self.embedding(input_ids)
        if self.config.char_dim > 0:
            if char_ids is None:
                raise ValueError("this model needs char_ids")
            x = torch.cat([x, self._char_features(char_ids)], dim=-1)
        x = self.dropout(x)
        # Packing keeps the backward LSTM from reading padding as if it were text.
        packed = pack_padded_sequence(x, lengths, batch_first=True, enforce_sorted=False)
        out, _ = self.lstm(packed)
        out, _ = pad_packed_sequence(out, batch_first=True, total_length=input_ids.size(1))
        out = self.dropout(out)
        logits = {h: self.heads[h](out) for h in HEADS}
        result = {"logits": logits}
        if all(f"labels_{h}" in labels for h in HEADS):
            if self.config.use_crf:
                result["loss"] = sum(self.crfs[h].nll(logits[h], labels[f"labels_{h}"], mask) for h in HEADS)
            else:
                result["loss"] = sum(
                    self.loss_fn(logits[h].reshape(-1, self.config.num_labels), labels[f"labels_{h}"].reshape(-1))
                    for h in HEADS
                )
        return result

    def decode(self, logits: dict, mask: torch.Tensor) -> dict[str, list[list[int]]]:
        """Label ids per head, cut to each sentence's length (Viterbi with a CRF, else argmax)."""
        lengths = mask.sum(1).tolist()
        if self.config.use_crf:
            return {h: self.crfs[h].decode(logits[h], mask) for h in HEADS}
        return {h: [row[:n] for row, n in zip(logits[h].argmax(-1).tolist(), lengths)] for h in HEADS}


def add_char_ids(batch: dict, items: list[list[list[int]]]) -> dict:
    """Pad per-word char id lists into batch['char_ids'] of shape [B, T, C]."""
    t = batch["input_ids"].size(1)
    c = max((len(w) for sent in items for w in sent), default=1)
    ids = torch.zeros(len(items), t, c, dtype=torch.long)
    for i, sent in enumerate(items):
        for j, w in enumerate(sent):
            ids[i, j, : len(w)] = torch.tensor(w)
    batch["char_ids"] = ids
    return batch


def collate_with_chars(batch: list[dict]) -> dict[str, torch.Tensor]:
    """bilstm_collate plus char ids, for items that carry a 'char_ids' list."""
    out = bilstm_collate([{k: v for k, v in b.items() if k != "char_ids"} for b in batch])
    if "char_ids" in batch[0]:
        add_char_ids(out, [b["char_ids"] for b in batch])
    return out


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
        char_ids = None
        if model.config.char_dim > 0:
            char_ids = add_char_ids(batch, [model.encode_chars(s or ["?"]) for s in chunk])["char_ids"].to(device)
        mask = batch["mask"].to(device)
        logits = model(batch["input_ids"].to(device), mask, char_ids)["logits"]
        ids = model.decode(logits, mask)
        for h in HEADS:
            out[h].extend([ID2LABEL[t] for t in row[: len(s)]] for row, s in zip(ids[h], chunk))
    return out

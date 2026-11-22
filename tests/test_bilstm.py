import pytest
import torch

from core.bilstm import BiLSTMConfig, BiLSTMTagger, load_checkpoint, predict_tags, save_checkpoint
from core.data import Vocab, bilstm_collate, bilstm_encode
from core.utils import set_seed

ROWS = [
    {"tokens": ["Strong", "Python", "skills"], "tags_skill": ["O", "O", "O"], "tags_knowledge": ["O", "B", "O"]},
    {"tokens": ["Design", "REST", "APIs", "and", "write", "tests"],
     "tags_skill": ["B", "I", "I", "O", "B", "I"], "tags_knowledge": ["O", "B", "I", "O", "O", "O"]},
]


def make():
    set_seed(0)
    vocab = Vocab.build([r["tokens"] for r in ROWS], min_freq=1)
    model = BiLSTMTagger(BiLSTMConfig(vocab_size=len(vocab), embedding_dim=8, hidden_dim=8, num_layers=1))
    return model, vocab


def test_padding_does_not_change_predictions():
    model, vocab = make()
    model.eval()
    short = bilstm_collate([bilstm_encode(ROWS[0], vocab)])
    padded = bilstm_collate([bilstm_encode(ROWS[0], vocab), bilstm_encode(ROWS[1], vocab)])
    a = model(short["input_ids"], short["mask"])["logits"]["skill"][0]
    b = model(padded["input_ids"], padded["mask"])["logits"]["skill"][0, :3]
    assert torch.allclose(a, b, atol=1e-6)


def test_can_overfit_two_sentences():
    model, vocab = make()
    batch = bilstm_collate([bilstm_encode(r, vocab) for r in ROWS])
    optim = torch.optim.Adam(model.parameters(), lr=0.05)
    model.train()
    for _ in range(150):
        loss = model(**batch)["loss"]
        optim.zero_grad()
        loss.backward()
        optim.step()
    model.dropout.p = 0.0
    tags = predict_tags(model, vocab, [r["tokens"] for r in ROWS])
    assert tags["skill"] == [r["tags_skill"] for r in ROWS]
    assert tags["knowledge"] == [r["tags_knowledge"] for r in ROWS]


def test_checkpoint_roundtrip(tmp_path):
    model, vocab = make()
    save_checkpoint(tmp_path, model, vocab, extra={"epoch": 1})
    loaded, loaded_vocab, extra = load_checkpoint(tmp_path)
    assert extra == {"epoch": 1} and loaded_vocab.itos == vocab.itos
    sents = [r["tokens"] for r in ROWS]
    model.eval()
    assert predict_tags(loaded, loaded_vocab, sents) == predict_tags(model, vocab, sents)


def test_missing_checkpoint_has_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="model.pt"):
        load_checkpoint(tmp_path / "nope")


def test_empty_sentence_predicts_empty():
    model, vocab = make()
    assert predict_tags(model, vocab, [[], ["Python"]])["skill"][0] == []

"""Uses a tiny randomly initialised DistilBERT so tests stay fast; the real tokenizer checks alignment."""
import pytest
import torch

transformers = pytest.importorskip("transformers")

from core.data import bert_collate, bert_encode  # noqa: E402
from core.distilbert import DistilBertTagger, load_checkpoint, predict_tags, save_checkpoint  # noqa: E402
from core.utils import set_seed  # noqa: E402

ROWS = [
    {"tokens": ["Strong", "PostgreSQL", "skills"], "tags_skill": ["O", "O", "O"], "tags_knowledge": ["O", "B", "O"]},
    {"tokens": ["Design", "REST", "APIs", "and", "write", "tests"],
     "tags_skill": ["B", "I", "I", "O", "B", "I"], "tags_knowledge": ["O", "B", "I", "O", "O", "O"]},
]


@pytest.fixture(scope="module")
def tokenizer():
    return transformers.AutoTokenizer.from_pretrained("distilbert-base-cased")


def tiny_model(tokenizer):
    set_seed(0)
    cfg = transformers.DistilBertConfig(vocab_size=tokenizer.vocab_size, dim=32, hidden_dim=64, n_layers=1,
                                        n_heads=2, max_position_embeddings=128)
    return DistilBertTagger(transformers.DistilBertModel(cfg), dropout=0.0)


def test_can_overfit_two_sentences(tokenizer):
    model = tiny_model(tokenizer)
    feats = [f for r in ROWS for f in bert_encode(r, tokenizer)]
    batch = bert_collate(feats, tokenizer.pad_token_id)
    optim = torch.optim.AdamW(model.parameters(), lr=3e-3)
    model.train()
    for _ in range(200):
        loss = model(**batch)["loss"]
        optim.zero_grad()
        loss.backward()
        optim.step()
    tags = predict_tags(model, tokenizer, [r["tokens"] for r in ROWS])
    assert tags["skill"] == [r["tags_skill"] for r in ROWS]
    assert tags["knowledge"] == [r["tags_knowledge"] for r in ROWS]


def test_predict_long_and_empty_sentences(tokenizer):
    model = tiny_model(tokenizer).eval()
    long = ["Kubernetes", "and", "PostgreSQL"] * 40
    tags = predict_tags(model, tokenizer, [long, [], ["Git"]], max_length=32)
    assert [len(t) for t in tags["skill"]] == [len(long), 0, 1]


def test_checkpoint_roundtrip(tmp_path, tokenizer):
    model = tiny_model(tokenizer).eval()
    save_checkpoint(tmp_path, model, tokenizer, max_length=128, extra={"epoch": 2})
    loaded, loaded_tok, meta = load_checkpoint(tmp_path)
    assert meta["extra"] == {"epoch": 2} and meta["max_length"] == 128
    sents = [r["tokens"] for r in ROWS]
    assert predict_tags(loaded, loaded_tok, sents) == predict_tags(model, tokenizer, sents)


def test_missing_checkpoint_has_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="weights.pt"):
        load_checkpoint(tmp_path)

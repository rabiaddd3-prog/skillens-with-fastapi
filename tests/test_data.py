import pytest

from core.data import (
    Vocab,
    align_labels,
    bert_collate,
    bert_encode,
    bilstm_collate,
    bilstm_encode,
    merge_windows,
    subword_preds_to_words,
    word_chunks,
)
from core.labels import IGNORE_INDEX, LABEL2ID

ROW = {
    "tokens": ["Experience", "with", "PostgreSQL", "and", "Kubernetes", "required"],
    "tags_skill": ["O", "O", "O", "O", "O", "O"],
    "tags_knowledge": ["O", "O", "B", "O", "B", "O"],
}


def test_vocab_built_from_train_with_unk(tmp_path):
    vocab = Vocab.build([["Python", "SQL"], ["python", "Git"]], min_freq=2)
    assert vocab.itos[:2] == ["<pad>", "<unk>"]
    assert vocab.encode(["PYTHON", "Rust"]) == [vocab.stoi["python"], 1]
    vocab.save(tmp_path / "vocab.json")
    assert Vocab.load(tmp_path / "vocab.json").itos == vocab.itos


def test_bilstm_collate_pads_and_masks():
    vocab = Vocab.build([ROW["tokens"]], min_freq=1)
    short = {"tokens": ["with"], "tags_skill": ["O"], "tags_knowledge": ["B"]}
    batch = bilstm_collate([bilstm_encode(ROW, vocab), bilstm_encode(short, vocab)])
    assert batch["input_ids"].shape == (2, 6)
    assert batch["mask"][1].tolist() == [True] + [False] * 5
    assert batch["labels_knowledge"][1].tolist() == [LABEL2ID["B"]] + [IGNORE_INDEX] * 5


def test_word_chunks_fit_limit_and_cover_all_words():
    counts = [3, 2, 4, 1, 5, 2]
    chunks = word_chunks(counts, max_subwords=6)
    assert chunks == [(0, 2), (2, 4), (4, 5), (5, 6)]
    assert all(sum(counts[s:e]) <= 6 for s, e in chunks)
    assert [i for s, e in chunks for i in range(s, e)] == list(range(len(counts)))


def test_word_chunks_single_long_word_and_empty():
    assert word_chunks([10], max_subwords=4) == [(0, 1)]
    assert word_chunks([], max_subwords=4) == [(0, 0)]


def test_align_labels_first_subword_only():
    word_ids = [None, 0, 1, 1, 1, 2, None]
    assert align_labels(word_ids, [0, 1, 2]) == [IGNORE_INDEX, 0, 1, IGNORE_INDEX, IGNORE_INDEX, 2, IGNORE_INDEX]


def test_subword_preds_to_words_handles_dropped_word():
    # word 1 produced no subwords -> predicted O
    assert subword_preds_to_words([None, 0, 0, 2, None], [9, 1, 2, 2, 9], num_words=3) == [1, LABEL2ID["O"], 2]


@pytest.fixture(scope="module")
def tokenizer():
    transformers = pytest.importorskip("transformers")
    return transformers.AutoTokenizer.from_pretrained("distilbert-base-cased")


def test_bert_encode_real_tokenizer_alignment(tokenizer):
    (feat,) = bert_encode(ROW, tokenizer)
    labelled = [(tokenizer.convert_ids_to_tokens(i), l)
                for i, l in zip(feat["input_ids"], feat["labels_knowledge"]) if l != IGNORE_INDEX]
    # one labelled position per word, in order, carrying that word's tag
    assert len(labelled) == len(ROW["tokens"])
    assert [l for _, l in labelled] == [LABEL2ID[t] for t in ROW["tags_knowledge"]]
    assert feat["labels_knowledge"][0] == IGNORE_INDEX and feat["labels_knowledge"][-1] == IGNORE_INDEX


def test_bert_long_sentence_windows_roundtrip(tokenizer):
    tokens = ["Kubernetes", "and", "PostgreSQL"] * 100  # ~ >512 subwords
    tags = ["B", "O", "B"] * 100
    row = {"tokens": tokens, "tags_skill": ["O"] * 300, "tags_knowledge": tags}
    feats = bert_encode(row, tokenizer, max_length=64)
    assert len(feats) > 1
    assert all(len(f["input_ids"]) <= 64 for f in feats)
    # feeding gold labels through the prediction path must reproduce the gold word tags
    word_preds = [subword_preds_to_words(f["word_ids"], f["labels_knowledge"], f["num_words"]) for f in feats]
    assert merge_windows(feats, word_preds, len(tokens)) == [LABEL2ID[t] for t in tags]
    batch = bert_collate(feats, tokenizer.pad_token_id)
    assert batch["input_ids"].shape[0] == len(feats)

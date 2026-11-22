from core.errors import classify_errors

TOKENS = [["Experience", "with", "Python", "and", "REST", "APIs"]]


def run(gold_k, pred_k):
    o = ["O"] * 6
    return classify_errors(TOKENS, {"skill": [o], "knowledge": [gold_k]}, {"skill": [o], "knowledge": [pred_k]})


def test_exact_match_is_no_error():
    tags = ["O", "O", "B", "O", "B", "I"]
    assert run(tags, tags) == []


def test_boundary_fp_fn_classified():
    gold = ["O", "O", "B", "O", "B", "I"]  # Python, REST APIs
    pred = ["B", "O", "O", "O", "B", "O"]  # Experience (fp), REST (boundary), Python missed (fn)
    errs = {(e["type"], e["pred"], e["gold"]) for e in run(gold, pred)}
    assert errs == {("fp", "Experience", None), ("boundary", "REST", "REST APIs"), ("fn", None, "Python")}


def test_boundary_gold_not_double_counted_as_fn():
    errs = run(["O", "O", "O", "O", "B", "I"], ["O", "O", "O", "O", "O", "B"])
    assert [e["type"] for e in errs] == ["boundary"]

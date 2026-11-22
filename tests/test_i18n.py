"""English/Turkish behaviour: message catalogue, translated quiz bank, localized API responses."""
import json
from pathlib import Path

import pytest

from core.cv import CVError, detect_skills
from core.i18n import MESSAGES, LocalizedError, msg, norm_lang
from core.matching import match_job
from core.quiz import QuizEngine, load_bank
from core.roadmap import build_roadmap
from tests.test_api import client  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]


def test_every_message_has_both_languages_and_same_placeholders():
    import re

    for key, texts in MESSAGES.items():
        assert set(texts) >= {"en", "tr"}, key
        assert set(re.findall(r"\{(\w+)\}", texts["en"])) <= set(re.findall(r"\{(\w+)\}", texts["tr"])) | {"pct"}, key


def test_norm_lang_and_localized_error():
    assert norm_lang("tr-TR") == "tr" and norm_lang("de") == "en" and norm_lang(None) == "en"
    with pytest.raises(CVError) as exc:
        detect_skills("   ")
    assert str(exc.value) == "The CV text is empty."
    assert exc.value.localized("tr") == "CV metni boş."
    assert isinstance(exc.value, LocalizedError)


def test_translation_file_covers_every_question():
    bank = load_bank()
    tr = json.loads((ROOT / "data" / "quiz_bank_tr.json").read_text(encoding="utf-8"))["questions"]
    assert set(tr) == {q["id"] for q in bank}
    for q in bank:
        assert len(tr[q["id"]]["options"]) == len(q["options"]), q["id"]
        assert tr[q["id"]]["question"].strip() and tr[q["id"]]["explanation"].strip()


def test_turkish_quiz_keeps_answer_key_aligned():
    engine = QuizEngine(seed=4)
    started = engine.start(["sql"], total=5, level="junior", lang="tr")
    tr = engine.translations["tr"]
    for pub, q in zip(started["questions"], engine.sessions[started["session_id"]].questions):
        assert pub["question"] == tr[q["id"]]["question"]
        # the option shown at the answer index is the translation of the correct English option
        original_correct = next(b for b in load_bank() if b["id"] == q["id"])["answer"]
        assert pub["options"][q["answer"]] == tr[q["id"]]["options"][original_correct]
    result = engine.submit(started["session_id"], {})
    assert result["review"][0]["explanation"] == tr[result["review"][0]["id"]]["explanation"]


def test_roadmap_and_notes_in_turkish():
    quiz = {"sql": {"correct": 1, "total": 5, "ratio": 0.2, "level": "senior"}}
    m = match_job(["SQL", "Kubernetes"], [], quiz, lang="tr")
    steps = build_roadmap(m, quiz_scores=quiz, courses={}, lang="tr")["steps"]
    sql = next(s for s in steps if s["id"] == "sql_fundamentals")
    assert sql["title"] == "SQL temelleri" and "senior seviye" in sql["reason"] and "%20" in sql["reason"]
    prereq = next(s for s in steps if s["kind"] == "prerequisite")
    assert "için ön koşul" in prereq["reason"]
    assert any("Quiz ile ölçülmedi" in n or "kanıta dayanıyor" in n for n in m["notes"])
    assert msg("road.no_gaps", "tr").startswith("Bu ilan için eksik yok")


def test_api_answers_in_requested_language(client):  # noqa: F811
    c, _ = client
    r = c.post("/cv/analyze-text", json={"text": " "}, headers={"X-Lang": "tr"})
    assert r.status_code == 422 and r.json()["detail"] == "CV metni boş."
    r = c.post("/cv/analyze-text", json={"text": " "})
    assert r.json()["detail"] == "The CV text is empty."
    q = c.post("/quiz/start", json={"topics": ["python"], "total": 3}, headers={"X-Lang": "tr"}).json()
    tr = json.loads((ROOT / "data" / "quiz_bank_tr.json").read_text(encoding="utf-8"))["questions"]
    assert all(x["question"] == tr[x["id"]]["question"] for x in q["questions"])
    names = c.get("/quiz/topics", headers={"X-Lang": "tr"}).json()["names"]
    assert names["algorithms"] == "Algoritmalar ve Veri Yapıları"


def test_job_import_errors_keep_502_and_translate(client):  # noqa: F811
    c, _ = client
    r = c.post("/jobs/import", json={"source": "greenhouse", "board": "bad name!"}, headers={"X-Lang": "tr"})
    assert r.status_code == 502 and "harf, rakam" in r.json()["detail"]
    r = c.post("/jobs/import", json={"source": "manual", "description": "short"})
    assert r.status_code == 422 and "too short" in r.json()["detail"]


def test_pdf_summary_in_turkish(client):  # noqa: F811
    import pymupdf

    c, _ = client
    jid = c.post("/jobs/import", json={"source": "manual", "title": "Backend",
                                       "description": "You know Python and SQL. Git is a plus."}).json()["imported"][0]["id"]
    r = c.post("/roadmap/pdf", json={"job_id": jid, "cv_skills": ["Python"], "quiz_scores": {}}, headers={"X-Lang": "tr"})
    text = pymupdf.open(stream=r.content, filetype="pdf")[0].get_text()
    assert "Öğrenme yol haritası" in text and "Skorlar" in text

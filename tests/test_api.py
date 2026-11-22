"""API tests with a fake tagger, so they run without a GPU or checkpoint."""
import pytest
from fastapi.testclient import TestClient

from tests.test_backend import fake_tagger


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLLENS_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("SKILLLENS_SKIP_MODEL", "1")
    from api import main
    from core.extractor import SkillExtractor

    with TestClient(main.app) as c:
        main.state.extractor = SkillExtractor(fake_tagger, model_name="fake")
        yield c, main


def test_health_and_missing_model_message(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLLENS_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("SKILLLENS_CHECKPOINT", str(tmp_path / "no-checkpoint"))
    monkeypatch.delenv("SKILLLENS_SKIP_MODEL", raising=False)
    from api import main

    with TestClient(main.app) as c:
        h = c.get("/health").json()
        assert h["model_loaded"] is False and "not found" in h["model_error"]
        r = c.post("/skills/extract", json={"text": "Python"})
        assert r.status_code == 503 and "not loaded" in r.json()["detail"]


def test_extract_and_jobs_flow(client):
    c, _ = client
    r = c.post("/skills/extract", json={"text": "Strong Python and SQL. Git is a plus."})
    assert r.status_code == 200 and r.json()["skills"] == ["Python", "SQL", "Git"]
    jobs = c.get("/jobs").json()
    assert len(jobs) >= 10 and all(j["is_demo"] for j in jobs)
    imp = c.post("/jobs/import", json={"source": "manual", "title": "Dev",
                                       "description": "We need Python, SQL and Git experience."}).json()
    assert imp["counts"]["created"] == 1
    again = c.post("/jobs/import", json={"source": "manual", "title": "Dev",
                                         "description": "We need Python, SQL and Git experience."}).json()
    assert again["counts"]["unchanged"] == 1
    assert c.post("/jobs/import", json={"source": "manual", "description": " "}).status_code == 422
    assert c.post("/jobs/import", json={"source": "greenhouse"}).status_code == 422
    assert c.get("/jobs/99999").status_code == 404


def test_demo_jobs_have_credited_photos(client):
    c, _ = client
    jobs = c.get("/jobs").json()
    demo = [j for j in jobs if j["is_demo"]]
    assert demo and all(j["image"] and j["image"]["photographer"] and j["image"]["page_url"] for j in demo)
    assert c.get(demo[0]["image"]["url"]).status_code == 200
    pasted = c.post("/jobs/import", json={"source": "manual", "title": "X",
                                          "description": "We need Python and SQL experience."}).json()["imported"][0]["id"]
    assert c.get(f"/jobs/{pasted}").json()["image"] is None


def test_cv_endpoints(client):
    c, _ = client
    r = c.post("/cv/analyze", files={"file": ("cv.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422 and "not a PDF" in r.json()["detail"]
    r = c.post("/cv/analyze-text", json={"text": "Experienced with Python and Git."})
    assert [s["skill"] for s in r.json()["skills"]] == ["Python", "Git"]


def test_quiz_match_roadmap_demo_flow(client):
    c, main = client
    jid = c.post("/jobs/import", json={"source": "manual", "title": "Backend",
                                       "description": "You know Python and SQL. Git is a plus."}).json()["imported"][0]["id"]
    started = c.post("/quiz/start", json={"job_id": jid, "total": 10}).json()
    assert {q["topic"] for q in started["questions"]} == {"python", "sql"}
    assert all("answer" not in q for q in started["questions"])
    key = {q["id"]: q["answer"] for q in main.state.quiz.sessions[started["session_id"]].questions}
    answers = {qid: (a if qid.startswith("py") else (a + 1) % 4) for qid, a in key.items()}
    scored = c.post("/quiz/submit", json={"session_id": started["session_id"], "answers": answers}).json()
    quiz_scores = scored["topics"]
    assert quiz_scores["sql"]["ratio"] == 0.0

    ranking = c.post("/matches", json={"cv_skills": ["Python", "Git"], "quiz_scores": quiz_scores}).json()["ranking"]
    assert ranking and ranking[0]["match"]["scores"]["combined"] is not None
    rm = c.post("/roadmap", json={"job_id": jid, "cv_skills": ["Python", "Git"], "quiz_scores": quiz_scores}).json()
    assert [s["id"] for s in rm["roadmap"]["steps"]] == ["sql_fundamentals"]
    git = next(s for s in rm["match"]["skills"] if s["skill"] == "Git")
    assert git["status"] == "cv_only"

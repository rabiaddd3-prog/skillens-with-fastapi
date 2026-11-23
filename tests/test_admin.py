"""Admin API: token check, overview, job management, import log, question bank."""
import pytest
from fastapi.testclient import TestClient

from tests.test_backend import fake_tagger

TOKEN = "test-admin-token"
H = {"X-Admin-Token": TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLLENS_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("SKILLLENS_SKIP_MODEL", "1")
    monkeypatch.setenv("SKILLLENS_ADMIN_TOKEN", TOKEN)
    from api import main
    from core.extractor import SkillExtractor

    with TestClient(main.app) as c:
        main.state.extractor = SkillExtractor(fake_tagger, model_name="fake")
        yield c, main


def test_admin_needs_the_token(client):
    c, _ = client
    assert c.get("/admin/api/stats").status_code == 401
    r = c.get("/admin/api/stats", headers={"X-Admin-Token": "wrong", "X-Lang": "tr"})
    assert r.status_code == 401 and "anahtar" in r.json()["detail"]
    assert c.get("/admin/api/stats", headers=H).status_code == 200


def test_admin_stats_count_usage(client):
    c, _ = client
    c.post("/skills/extract", json={"text": "Python and SQL."})
    c.post("/skills/extract", json={"text": ""})  # 422
    s = c.get("/admin/api/stats", headers=H).json()
    assert s["jobs"] >= 10 and s["by_source"]["demo"] == s["jobs"] and s["model"] == "fake"
    assert sum(s["quiz_bank"]["python"].values()) == 45
    u = {row["route"]: row for row in s["usage"]}["POST /skills/extract"]
    assert u["count"] == 2 and u["errors"] == 1 and u["avg_ms"] >= 0


def test_admin_job_management_and_import_log(client):
    c, _ = client
    imp = c.post("/jobs/import", json={"source": "manual", "title": "Dev",
                                       "description": "We need Python, SQL and Git experience."}).json()
    jid = imp["imported"][0]["id"]
    c.post("/jobs/import", json={"source": "greenhouse"})  # no board: logged as an error
    log = c.get("/admin/api/imports", headers=H).json()
    assert [e["status"] for e in log[:2]] == ["error", "ok"] and log[1]["created"] == 1

    r = c.post(f"/admin/api/jobs/{jid}/reextract", headers=H).json()
    assert r["skills"] == ["Python", "SQL", "Git"]
    jobs = {j["id"]: j for j in c.get("/admin/api/jobs", headers=H).json()}
    assert jobs[jid]["extracted_by"] == "fake"
    assert any(j["id"] == jid and j["skills"] for j in c.get("/jobs").json())

    assert c.delete(f"/admin/api/jobs/{jid}", headers=H).json() == {"deleted": jid}
    assert c.delete(f"/admin/api/jobs/{jid}", headers=H).status_code == 404
    assert c.get(f"/jobs/{jid}").status_code == 404


def test_admin_quiz_bank_filters_and_shows_answers(client):
    c, _ = client
    qs = c.get("/admin/api/quiz", params={"topic": "sql", "level": "senior"}, headers=H).json()
    assert len(qs) == 15 and all(q["topic"] == "sql" and q["level"] == "senior" for q in qs)
    assert all(0 <= q["answer"] < len(q["options"]) for q in qs)
    tr = c.get("/admin/api/quiz", params={"topic": "sql", "level": "senior"}, headers=H | {"X-Lang": "tr"}).json()
    assert tr[0]["id"] == qs[0]["id"] and tr[0]["question"] != qs[0]["question"]

"""Accounts, JWT sign-in, the user's saved data, and job CRUD with ownership."""
import pytest
from fastapi.testclient import TestClient

from tests.test_backend import fake_tagger

JOB = {"title": "Backend Developer", "company": "Acme", "location": "Istanbul",
       "description": "We need Python, SQL and Git for our backend team."}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SKILLLENS_DB", str(tmp_path / "jobs.db"))
    monkeypatch.setenv("SKILLLENS_SKIP_MODEL", "1")
    monkeypatch.setenv("SKILLLENS_JWT_SECRET", "test-jwt-secret")
    from api import main
    from core.extractor import SkillExtractor

    with TestClient(main.app) as c:
        main.state.extractor = SkillExtractor(fake_tagger, model_name="fake")
        yield c


def signup(c, email="rabia@example.com", password="secret-pass-1", name="Rabia"):
    r = c.post("/auth/register", json={"email": email, "password": password, "name": name})
    assert r.status_code == 201, r.text
    tok = c.post("/auth/token", data={"username": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def test_register_login_and_me(client):
    c = client
    h = signup(c)
    me = c.get("/users/me", headers=h).json()
    assert me["email"] == "rabia@example.com" and me["name"] == "Rabia" and "password_hash" not in me
    assert c.post("/auth/register", json={"email": "RABIA@example.com", "password": "another-pass", "name": "x"}
                  ).status_code == 409                       # e-mail is unique, case-insensitive
    assert c.post("/auth/register", json={"email": "not-an-email", "password": "secret-pass-1", "name": "x"}
                  ).status_code == 422
    assert c.post("/auth/register", json={"email": "a@example.com", "password": "short", "name": "x"}
                  ).status_code == 422                       # at least 8 characters
    bad = c.post("/auth/token", data={"username": "rabia@example.com", "password": "wrong-password"},
                 headers={"X-Lang": "tr"})
    assert bad.status_code == 401 and "yanlış" in bad.json()["detail"]


def test_protected_endpoints_need_a_valid_token(client):
    c = client
    assert c.get("/users/me").status_code == 401
    assert c.get("/users/me", headers={"Authorization": "Bearer nonsense"}).status_code == 401
    assert c.post("/jobs", json=JOB).status_code == 401


def test_change_name_and_password(client):
    c = client
    h = signup(c)
    assert c.patch("/users/me", json={"name": "Rabia D.", "password": "new-secret-99"}, headers=h).json()["name"] == "Rabia D."
    assert c.post("/auth/token", data={"username": "rabia@example.com", "password": "secret-pass-1"}).status_code == 401
    assert c.post("/auth/token", data={"username": "rabia@example.com", "password": "new-secret-99"}).status_code == 200


def test_profile_quiz_results_and_roadmap_progress(client):
    c = client
    h = signup(c)
    assert c.get("/users/me/profile", headers=h).json() == {"cv_skills": [], "updated_at": None}
    p = c.put("/users/me/profile", json={"cv_skills": ["Python", "Git", "Python"]}, headers=h).json()
    assert p["cv_skills"] == ["Python", "Git"]               # duplicates dropped
    assert c.put("/users/me/profile", json={"cv_skills": ["Cobol++"]}, headers=h).status_code == 422

    r = c.post("/users/me/quiz-results", json={"level": "junior", "correct": 7, "total": 10,
                                               "scores": {"python": {"correct": 7, "total": 10, "ratio": 0.7}}},
               headers=h)
    assert r.status_code == 201 and r.json()["scores"]["python"]["ratio"] == 0.7
    assert c.post("/users/me/quiz-results", json={"correct": 11, "total": 10}, headers=h).status_code == 422
    results = c.get("/users/me/quiz-results", headers=h).json()
    assert len(results) == 1
    assert c.delete(f"/users/me/quiz-results/{results[0]['id']}", headers=h).status_code == 204
    assert c.get("/users/me/quiz-results", headers=h).json() == []

    assert c.get("/users/me/roadmaps/1", headers=h).json()["done"] == []
    c.put("/users/me/roadmaps/1", json={"done": ["sql_fundamentals"]}, headers=h)
    assert c.get("/users/me/roadmaps/1", headers=h).json()["done"] == ["sql_fundamentals"]
    assert [r["job_id"] for r in c.get("/users/me/roadmaps", headers=h).json()] == [1]


def test_users_cannot_see_each_others_data(client):
    c = client
    a, b = signup(c, "a@example.com"), signup(c, "b@example.com")
    c.put("/users/me/profile", json={"cv_skills": ["Python"]}, headers=a)
    rid = c.post("/users/me/quiz-results", json={"correct": 1, "total": 2}, headers=a).json()["id"]
    assert c.get("/users/me/profile", headers=b).json()["cv_skills"] == []
    assert c.get("/users/me/quiz-results", headers=b).json() == []
    assert c.delete(f"/users/me/quiz-results/{rid}", headers=b).status_code == 404


def test_saved_jobs(client):
    c = client
    h = signup(c)
    jid = c.get("/jobs").json()[0]["id"]
    r = c.post("/users/me/saved-jobs", json={"job_id": jid, "note": "apply next week"}, headers=h)
    assert r.status_code == 201 and r.json()["title"]
    assert c.post("/users/me/saved-jobs", json={"job_id": jid}, headers=h).status_code == 409
    assert c.post("/users/me/saved-jobs", json={"job_id": 99999}, headers=h).status_code == 404
    assert [s["job_id"] for s in c.get("/users/me/saved-jobs", headers=h).json()] == [jid]
    assert c.delete(f"/users/me/saved-jobs/{jid}", headers=h).status_code == 204
    assert c.get("/users/me/saved-jobs", headers=h).json() == []


def test_job_crud_and_ownership(client):
    c = client
    owner, other = signup(c, "owner@example.com"), signup(c, "other@example.com")
    r = c.post("/jobs", json=JOB, headers=owner)
    assert r.status_code == 201
    job = r.json()
    assert job["source"] == "manual" and job["owner_id"] is not None and job["title"] == "Backend Developer"
    jid = job["id"]
    assert c.get(f"/jobs/{jid}").json()["extraction"]["skills"] == ["Python", "SQL", "Git"]

    assert c.patch(f"/jobs/{jid}", json={"title": "Senior Backend Developer"}, headers=owner).json()["title"] == \
        "Senior Backend Developer"
    put = c.put(f"/jobs/{jid}", json={**JOB, "description": "Java and Docker for our platform team."}, headers=owner)
    assert put.status_code == 200 and put.json()["extracted"] is False        # new text -> read again
    assert c.get(f"/jobs/{jid}").json()["extraction"]["skills"] == ["Java", "Docker"]

    assert c.patch(f"/jobs/{jid}", json={"title": "x" * 3}, headers=other).status_code == 403
    assert c.delete(f"/jobs/{jid}", headers=other).status_code == 403
    demo_id = next(j["id"] for j in c.get("/jobs").json() if j["is_demo"])
    assert c.delete(f"/jobs/{demo_id}", headers=owner).status_code == 403   # demo jobs are read-only
    assert c.patch(f"/jobs/{jid}", json={"description": "too short"}, headers=owner).status_code == 422

    assert c.delete(f"/jobs/{jid}", headers=owner).status_code == 204
    assert c.get(f"/jobs/{jid}").status_code == 404
    assert c.delete(f"/jobs/{jid}", headers=owner).status_code == 404


def test_job_list_filters_and_pagination(client):
    c = client
    all_jobs = c.get("/jobs")
    total = int(all_jobs.headers["X-Total-Count"])
    assert total == len(all_jobs.json()) >= 10
    page = c.get("/jobs", params={"skip": 2, "limit": 3})
    assert len(page.json()) == 3 and page.headers["X-Total-Count"] == str(total)
    assert [j["id"] for j in page.json()] == [j["id"] for j in all_jobs.json()[2:5]]
    assert all(j["source"] == "demo" for j in c.get("/jobs", params={"source": "demo"}).json())
    found = c.get("/jobs", params={"q": "backend"}).json()
    assert found and all("backend" in (j["title"] + (j["company"] or "") + " ".join(j["skills"])).lower() for j in found)
    for j in all_jobs.json():                      # read every job once, so the skill lists are filled
        c.get(f"/jobs/{j['id']}")
    with_python = c.get("/jobs", params={"skill": "python", "limit": 2})
    assert len(with_python.json()) == 2 and all("Python" in j["skills"] for j in with_python.json())
    assert int(with_python.headers["X-Total-Count"]) >= 2
    assert c.get("/jobs", params={"limit": 0}).status_code == 422


def test_delete_account_removes_its_data(client):
    c = client
    h = signup(c)
    c.put("/users/me/profile", json={"cv_skills": ["Python"]}, headers=h)
    jid = c.post("/jobs", json=JOB, headers=h).json()["id"]
    assert c.delete("/users/me", headers=h).status_code == 204
    assert c.get("/users/me", headers=h).status_code == 401
    assert c.get(f"/jobs/{jid}").json()["owner_id"] is None            # the job stays, without an owner
    h2 = signup(c)                                                    # the e-mail can be used again
    assert c.get("/users/me/profile", headers=h2).json()["cv_skills"] == []


def test_openapi_lists_routers_and_bearer_auth(client):
    spec = client.get("/openapi.json").json()
    tags = {t for p in spec["paths"].values() for o in p.values() for t in o.get("tags", [])}
    assert {"auth", "users", "jobs", "cv", "skills", "quiz", "matching", "admin", "system"} <= tags
    assert spec["components"]["securitySchemes"]["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == "/auth/token"
    assert client.get("/redoc").status_code == 200

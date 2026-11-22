"""SkillLens FastAPI backend. The web frontend (web/) is served from the same app.

Run:  python -m uvicorn api.main:app --reload
Config (environment variables):
  SKILLLENS_MODEL       distilbert | bilstm           (default distilbert)
  SKILLLENS_CHECKPOINT  path to the checkpoint dir     (default checkpoints/<model>)
  SKILLLENS_DB          SQLite path for the job catalog (default data/jobs.db)
  SKILLLENS_DEVICE      auto | cpu | cuda | mps         (default auto)
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from core.cv import MAX_PDF_BYTES, CVError, detect_skills, pdf_to_text  # noqa: E402
from core.jobs import JobImportError, JobStore, demo_jobs, fetch_greenhouse, fetch_lever, manual_job  # noqa: E402
from core.matching import match_job, rank_jobs  # noqa: E402
from core.quiz import QuizEngine, QuizError  # noqa: E402
from core.roadmap import build_roadmap  # noqa: E402
from core.skills import default_dictionary  # noqa: E402


class State:
    extractor = None
    extractor_error: str | None = None
    store: JobStore | None = None
    quiz: QuizEngine | None = None


state = State()


def load_extractor() -> None:
    from core.extractor import SkillExtractor
    from core.utils import pick_device

    kind = os.environ.get("SKILLLENS_MODEL", "distilbert")
    path = os.environ.get("SKILLLENS_CHECKPOINT", str(ROOT / "checkpoints" / kind))
    try:
        state.extractor = SkillExtractor.from_checkpoint(path, kind, pick_device(os.environ.get("SKILLLENS_DEVICE", "auto")))
        state.extractor_error = None
    except (FileNotFoundError, ValueError) as exc:
        state.extractor, state.extractor_error = None, str(exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.store = JobStore(os.environ.get("SKILLLENS_DB", ROOT / "data" / "jobs.db"))
    for job in demo_jobs():  # demo listings are always available offline
        state.store.upsert(job)
    state.quiz = QuizEngine()
    if os.environ.get("SKILLLENS_SKIP_MODEL") != "1":
        load_extractor()
    yield


app = FastAPI(title="SkillLens API", version="0.1.0", lifespan=lifespan)


def extractor():
    if state.extractor is None:
        raise HTTPException(503, f"Skill extraction model is not loaded: {state.extractor_error or 'not configured'}")
    return state.extractor


def job_extraction(job: dict) -> dict:
    """Cached per job; recomputed when the job text, the model or the skill dictionary changes."""
    ex = job["extraction"]
    if (ex is None or ex.get("model") != extractor().model_name
            or ex.get("dictionary_version") != extractor().dictionary.version):
        job["extraction"] = extractor().extract(job["description"])
        state.store.set_extraction(job["id"], job["extraction"])
    return job["extraction"]


# ------------------------------------------------------------------ schemas

class TextIn(BaseModel):
    text: str = Field(..., min_length=1)


class JobIn(BaseModel):
    source: str = Field("manual", pattern="^(manual|greenhouse|lever)$")
    title: str | None = None
    company: str | None = None
    description: str | None = None
    board: str | None = Field(None, description="Greenhouse board token or Lever company name")
    limit: int = Field(20, ge=1, le=100)


class QuizStartIn(BaseModel):
    topics: list[str] = []
    job_id: int | None = None
    total: int = Field(25, ge=1, le=80)


class QuizSubmitIn(BaseModel):
    session_id: str
    answers: dict[str, int]


class Evidence(BaseModel):
    cv_skills: list[str] = []
    quiz_scores: dict[str, dict] = {}


class MatchIn(Evidence):
    job_ids: list[int] | None = None


class RoadmapIn(Evidence):
    job_id: int


# ------------------------------------------------------------------ endpoints

@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": state.extractor is not None,
            "model": state.extractor.model_name if state.extractor else None, "model_error": state.extractor_error,
            "jobs": len(state.store.list()), "quiz_topics": state.quiz.topics()}


@app.get("/skills/dictionary")
def skills_dictionary():
    d = default_dictionary()
    return {"topics": d.topics, "skills": [{"name": s.name, "category": s.category, "topic": s.topic}
                                           for s in d.skills.values()]}


@app.post("/skills/extract")
def skills_extract(body: TextIn):
    return extractor().extract(body.text)


@app.post("/cv/analyze")
async def cv_analyze(file: UploadFile = File(...)):
    """Text-based PDF upload. Nothing is stored. For scanned CVs use /cv/analyze-text."""
    try:
        cv_text = pdf_to_text(await file.read(MAX_PDF_BYTES + 1))
        return {"skills": detect_skills(cv_text), "characters": len(cv_text)}
    except CVError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/cv/analyze-text")
def cv_analyze_text(body: TextIn):
    try:
        return {"skills": detect_skills(body.text), "characters": len(body.text)}
    except CVError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/jobs/import")
def jobs_import(body: JobIn):
    try:
        if body.source == "manual":
            jobs = [manual_job(body.title or "Untitled job", body.description or "", body.company)]
        elif not body.board:
            raise HTTPException(422, "A board / company name is required for this source.")
        elif body.source == "greenhouse":
            jobs = fetch_greenhouse(body.board, body.limit)
        else:
            jobs = fetch_lever(body.board, body.limit)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except JobImportError as exc:
        raise HTTPException(502, str(exc)) from exc
    results = [dict(zip(("id", "status"), state.store.upsert(j))) for j in jobs]
    counts = {s: sum(r["status"] == s for r in results) for s in ("created", "updated", "unchanged")}
    return {"source": body.source, "imported": results, "counts": counts}


def job_image(job: dict) -> dict | None:
    """Representative stock photo for a demo job (data/job_images.json), with its credit."""
    import json

    path = ROOT / "data" / "job_images.json"
    if job["source"] != "demo" or not path.exists():
        return None
    entry = json.loads(path.read_text(encoding="utf-8")).get("images", {}).get(job["source_id"])
    if not entry or not (ROOT / "web" / "img" / "jobs" / entry["file"]).exists():
        return None
    return {"url": f"/static/img/jobs/{entry['file']}", "alt": entry["alt"], "photographer": entry["photographer"],
            "source": entry["source"], "page_url": entry["page_url"]}


@app.get("/jobs")
def jobs_list(source: str | None = None):
    return [{k: v for k, v in j.items() if k != "extraction"}
            | {"extracted": j["extraction"] is not None, "image": job_image(j)}
            for j in state.store.list(source)]


@app.get("/jobs/{job_id}")
def jobs_get(job_id: int):
    job = state.store.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    job["extraction"] = job_extraction(job)
    job["image"] = job_image(job)
    return job


@app.get("/quiz/topics")
def quiz_topics():
    return {"topics": state.quiz.topics(), "names": default_dictionary().topics}


@app.post("/quiz/start")
def quiz_start(body: QuizStartIn):
    topics = list(body.topics)
    if body.job_id is not None:
        job = state.store.get(body.job_id)
        if job is None:
            raise HTTPException(404, "Job not found.")
        d = default_dictionary()
        job_topics = [t for t in dict.fromkeys(d.topic_of(s) for s in job_extraction(job)["skills"]) if t]
        topics += [t for t in job_topics if t in state.quiz.by_topic and t not in topics]
        if not topics:
            raise HTTPException(422, "This job has no skills covered by the quiz bank. Choose topics manually.")
    try:
        return state.quiz.start(topics, body.total)
    except QuizError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/quiz/submit")
def quiz_submit(body: QuizSubmitIn):
    try:
        return state.quiz.submit(body.session_id, body.answers)
    except QuizError as exc:
        raise HTTPException(422, str(exc)) from exc


def _job_skills(job_id: int) -> tuple[dict, list[str]]:
    job = state.store.get(job_id)
    if job is None:
        raise HTTPException(404, f"Job {job_id} not found.")
    return job, job_extraction(job)["skills"]


@app.post("/matches")
def matches(body: MatchIn):
    ids = body.job_ids or [j["id"] for j in state.store.list()]
    jobs = []
    for jid in ids:
        job, skills = _job_skills(jid)
        jobs.append({"id": job["id"], "title": job["title"], "company": job["company"], "source": job["source"],
                     "is_demo": job["is_demo"], "url": job["url"], "image": job_image(job), "skills": skills})
    return {"ranking": rank_jobs(jobs, body.cv_skills, body.quiz_scores)}


@app.post("/roadmap")
def roadmap(body: RoadmapIn):
    job, skills = _job_skills(body.job_id)
    result = match_job(skills, body.cv_skills, body.quiz_scores)
    return {"job": {"id": job["id"], "title": job["title"], "company": job["company"]},
            "match": result, "roadmap": build_roadmap(result, body.cv_skills, body.quiz_scores)}


@app.post("/roadmap/pdf")
def roadmap_pdf(body: RoadmapIn):
    """Same inputs as /roadmap; returns a one-page PDF summary to download."""
    from fastapi.responses import Response

    from core.summary import summary_pdf

    job, skills = _job_skills(body.job_id)
    result = match_job(skills, body.cv_skills, body.quiz_scores)
    pdf = summary_pdf(job, result, build_roadmap(result, body.cv_skills, body.quiz_scores))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="skilllens_job{job["id"]}.pdf"'})


@app.get("/results/comparison")
def results_comparison():
    """Measured test-set comparison written by scripts/evaluate.py (404 until it has been run)."""
    import json

    path = ROOT / "results" / "test_metrics.json"
    if not path.exists():
        raise HTTPException(404, "No evaluation results yet. Run scripts/evaluate.py first.")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"test_sentences": data["test_sentences"], "device": data["run"]["device"],
            "latency_setup": {k: data["run"]["args"][k] for k in ("latency_sentences", "warmup")},
            "models": {name: {k: m[k] for k in ("scores", "latency", "error_counts", "parameters", "best_val_epoch")}
                       for name, m in data["models"].items()}}


# ------------------------------------------------------------------ frontend

WEB = ROOT / "web"
if WEB.exists():
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        # no-cache: the page links versioned CSS/JS, so a fresh page always pulls the current assets
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

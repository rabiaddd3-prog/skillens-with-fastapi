"""SkillLens FastAPI backend. The web frontend (web/) is served from the same app.

Run:  python -m uvicorn api.main:app --reload
Config (environment variables):
  SKILLLENS_MODEL       distilbert | bilstm           (default distilbert)
  SKILLLENS_CHECKPOINT  path to the checkpoint dir     (default checkpoints/<model>)
  SKILLLENS_DB          SQLite path for the job catalog (default data/jobs.db)
  SKILLLENS_DEVICE      auto | cpu | cuda | mps         (default auto)
  SKILLLENS_ADMIN_TOKEN token for /admin                (default: random, written to runs/admin_token.txt)
  SKILLLENS_AUTO_IMPORT boards imported on a schedule, e.g. "greenhouse:gitlab,lever:acme" (default: none)
  SKILLLENS_IMPORT_HOURS hours between scheduled imports (default 24; the first round runs at start)
  SKILLLENS_EMBED       0 turns the Sentence-BERT fallback for unmatched spans off (default on)
  SKILLLENS_EMBED_THRESHOLD cosine similarity needed for that fallback (default 0.75)
"""
from __future__ import annotations

import asyncio
import os
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from core.cv import MAX_PDF_BYTES, CVError, detect_skills, pdf_to_text  # noqa: E402
from core.i18n import LocalizedError, msg, norm_lang  # noqa: E402
from core.jobs import JobImportError, JobStore, demo_jobs, fetch_greenhouse, fetch_lever, manual_job  # noqa: E402
from core.matching import match_job, rank_jobs  # noqa: E402
from core.quiz import QuizEngine, QuizError  # noqa: E402
from core.roadmap import build_roadmap  # noqa: E402
from core.skills import default_dictionary  # noqa: E402


class State:
    extractor = None
    extractor_error: str | None = None
    # Both models, for the live side-by-side comparison; a missing checkpoint just leaves a gap.
    models: dict = {}
    store: JobStore | None = None
    quiz: QuizEngine | None = None
    admin_token: str = ""
    started: float = 0.0
    usage: dict = {}   # route -> {"count", "errors", "total_ms"}; in memory, reset on restart
    auto_import: dict = {}  # {"boards": [(source, board)], "every_hours", "last_run", "next_run"}


state = State()


def setup_admin_token() -> None:
    token = os.environ.get("SKILLLENS_ADMIN_TOKEN")
    if not token:
        token = secrets.token_urlsafe(12)
        path = ROOT / "runs" / "admin_token.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text(token + "\n", encoding="utf-8")
        print(f"SkillLens admin token (also in {path}): {token}", flush=True)
    state.admin_token = token


def warm_extractions() -> None:
    """Extract every job once at start, so the job cards can show their skills straight away."""
    for job in state.store.list():
        try:
            job_extraction(job)
        except Exception:  # noqa: BLE001 - a bad job must not stop the server
            pass


def load_extractor() -> None:
    from core.extractor import SkillExtractor
    from core.utils import pick_device

    device = pick_device(os.environ.get("SKILLLENS_DEVICE", "auto"))
    kind = os.environ.get("SKILLLENS_MODEL", "distilbert")
    path = os.environ.get("SKILLLENS_CHECKPOINT", str(ROOT / "checkpoints" / kind))
    try:
        state.extractor = SkillExtractor.from_checkpoint(path, kind, device)
        state.extractor_error = None
    except (FileNotFoundError, ValueError) as exc:
        state.extractor, state.extractor_error = None, str(exc)
    state.models = {kind: state.extractor} if state.extractor else {}
    if "SKILLLENS_CHECKPOINT" not in os.environ:  # a custom checkpoint: no side-by-side comparison
        for other in ("bilstm", "distilbert"):
            if other not in state.models and (ROOT / "checkpoints" / other).exists():
                try:
                    state.models[other] = SkillExtractor.from_checkpoint(ROOT / "checkpoints" / other, other, device)
                except (FileNotFoundError, ValueError):
                    pass
    if state.models:
        from core.embed_normalize import load_default

        embedder = load_default(device=str(device))
        for m in state.models.values():
            m.embedder = embedder


def parse_auto_import(value: str | None) -> list[tuple[str, str]]:
    """'greenhouse:gitlab, lever:acme' -> [("greenhouse", "gitlab"), ("lever", "acme")]; bad items are skipped."""
    boards = []
    for item in (value or "").split(","):
        source, _, board = item.strip().partition(":")
        if source in ("greenhouse", "lever") and board.strip():
            boards.append((source, board.strip()))
    return boards


def import_board(source: str, board: str, limit: int = 30, message: str | None = None) -> dict:
    """Fetch one board, upsert its jobs and log the attempt. Raises JobImportError on failure."""
    fetch = fetch_greenhouse if source == "greenhouse" else fetch_lever
    try:
        jobs = fetch(board, limit)
    except JobImportError as exc:
        state.store.log_import(source, board, "error", message=exc.localized("en"))
        raise
    results = [dict(zip(("id", "status"), state.store.upsert(j))) for j in jobs]
    counts = {s: sum(r["status"] == s for r in results) for s in ("created", "updated", "unchanged")}
    state.store.log_import(source, board, "ok", counts, message)
    return {"results": results, "counts": counts}


def run_scheduled_imports() -> None:
    """One round of the scheduled import (SKILLLENS_AUTO_IMPORT); new jobs are read by the model right away."""
    for source, board in state.auto_import.get("boards", []):
        try:
            import_board(source, board, message="scheduled")
        except JobImportError:
            pass  # already logged; the next board still runs
    state.auto_import["last_run"] = time.time()
    if state.extractor is not None:
        warm_extractions()


async def auto_import_loop() -> None:
    hours = state.auto_import["every_hours"]
    while True:
        await asyncio.to_thread(run_scheduled_imports)
        state.auto_import["next_run"] = time.time() + hours * 3600
        await asyncio.sleep(hours * 3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.store = JobStore(os.environ.get("SKILLLENS_DB", ROOT / "data" / "jobs.db"))
    for job in demo_jobs():  # demo listings are always available offline
        state.store.upsert(job)
    state.quiz = QuizEngine()
    state.started, state.usage = time.time(), {}
    setup_admin_token()
    if os.environ.get("SKILLLENS_SKIP_MODEL") != "1":
        load_extractor()
        if state.extractor is not None:
            warm_extractions()
    boards = parse_auto_import(os.environ.get("SKILLLENS_AUTO_IMPORT"))
    task = None
    state.auto_import = {}
    if boards:
        state.auto_import = {"boards": boards, "every_hours": float(os.environ.get("SKILLLENS_IMPORT_HOURS", "24")),
                             "last_run": None, "next_run": None}
        task = asyncio.create_task(auto_import_loop())
    yield
    if task is not None:
        task.cancel()


app = FastAPI(title="SkillLens API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def count_usage(request: Request, call_next):
    """Request count, error count and time per API route, for the admin overview."""
    t0 = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path and not path.startswith(("/static", "/admin")) and path not in ("/", "/health"):
        u = state.usage.setdefault(f"{request.method} {path}", {"count": 0, "errors": 0, "total_ms": 0.0})
        u["count"] += 1
        u["errors"] += response.status_code >= 400
        u["total_ms"] += (time.perf_counter() - t0) * 1000
    return response


def get_lang(x_lang: str | None = Header(None)) -> str:
    """Language of user-facing texts, sent by the frontend as the X-Lang header (en | tr)."""
    return norm_lang(x_lang)


def http_error(status: int, exc: LocalizedError, lang: str) -> HTTPException:
    return HTTPException(status, exc.localized(lang))


def extractor(lang: str = "en"):
    if state.extractor is None:
        raise HTTPException(503, msg("model.not_loaded", lang, reason=state.extractor_error or "not configured"))
    return state.extractor


def job_extraction(job: dict, lang: str = "en") -> dict:
    """Cached per job; recomputed when the job text, the model or the skill dictionary changes."""
    ex = job["extraction"]
    model = extractor(lang)
    embedding = {"model": model.embedder.model_name, "threshold": model.embedder.threshold} if model.embedder else None
    if (ex is None or ex.get("model") != model.model_name
            or ex.get("dictionary_version") != model.dictionary.version
            or ex.get("embedding") != embedding):
        job["extraction"] = model.extract(job["description"])
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
    level: str = Field("mid", pattern="^(junior|mid|senior)$")


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
    return {"status": "ok", "model_loaded": state.extractor is not None, "models": sorted(state.models),
            "model": state.extractor.model_name if state.extractor else None, "model_error": state.extractor_error,
            "jobs": sum(is_listed(j) for j in state.store.list()), "quiz_topics": state.quiz.topics()}


@app.get("/skills/dictionary")
def skills_dictionary(lang: str = Depends(get_lang)):
    d = default_dictionary()
    return {"topics": {t: msg(f"topic.{t}", lang) for t in d.topics}, "skills": [{"name": s.name, "category": s.category, "topic": s.topic,
                                                       "aliases": d.aliases.get(s.name, [])}
                                           for s in d.skills.values()]}


@app.post("/skills/extract")
def skills_extract(body: TextIn, lang: str = Depends(get_lang)):
    return extractor(lang).extract(body.text)


@app.post("/skills/compare")
def skills_compare(body: TextIn, lang: str = Depends(get_lang)):
    """Run BiLSTM and DistilBERT on the same text (model output only, no dictionary fallback).
    Returns each model's spans, its server-side time, and the spans only one model found."""
    import time

    if len(state.models) < 2:
        raise HTTPException(503, msg("model.not_loaded", lang, reason="both checkpoints are needed for a comparison"))
    out = {}
    for name in ("bilstm", "distilbert"):
        model = state.models[name]
        model.extract(body.text[:200], use_dictionary=False)  # warm-up so the timing is not the first call
        t0 = time.perf_counter()
        result = model.extract(body.text, use_dictionary=False)
        result["ms"] = (time.perf_counter() - t0) * 1000
        out[name] = result
    key = lambda m: (m["start"], m["end"], m["type"])  # noqa: E731
    spans = {n: {key(m) for m in r["mentions"]} for n, r in out.items()}
    for n, other in (("bilstm", "distilbert"), ("distilbert", "bilstm")):
        out[n]["only_here"] = [m for m in out[n]["mentions"] if key(m) not in spans[other]]
    out["agree"] = len(spans["bilstm"] & spans["distilbert"])
    return out


@app.post("/cv/analyze")
async def cv_analyze(file: UploadFile = File(...), lang: str = Depends(get_lang)):
    """Text-based PDF upload. Nothing is stored. For scanned CVs use /cv/analyze-text."""
    try:
        cv_text = pdf_to_text(await file.read(MAX_PDF_BYTES + 1))
        return {"skills": detect_skills(cv_text), "characters": len(cv_text)}
    except CVError as exc:
        raise http_error(422, exc, lang) from exc


@app.post("/cv/analyze-text")
def cv_analyze_text(body: TextIn, lang: str = Depends(get_lang)):
    try:
        return {"skills": detect_skills(body.text), "characters": len(body.text)}
    except CVError as exc:
        raise http_error(422, exc, lang) from exc


@app.post("/jobs/import")
def jobs_import(body: JobIn, lang: str = Depends(get_lang)):
    try:
        if body.source == "manual":
            jobs = [manual_job(body.title or "Untitled job", body.description or "", body.company)]
        elif not body.board:
            raise LocalizedError("job.board_required")
        else:
            done = import_board(body.source, body.board, body.limit)
            return {"source": body.source, "imported": done["results"], "counts": done["counts"]}
    except JobImportError as exc:  # logged inside import_board
        raise http_error(502, exc, lang) from exc
    except LocalizedError as exc:
        state.store.log_import(body.source, body.board, "error", message=exc.localized("en"))
        raise http_error(422, exc, lang) from exc
    results = [dict(zip(("id", "status"), state.store.upsert(j))) for j in jobs]
    counts = {s: sum(r["status"] == s for r in results) for s in ("created", "updated", "unchanged")}
    state.store.log_import(body.source, body.board, "ok", counts)
    return {"source": body.source, "imported": results, "counts": counts}


def is_listed(job: dict) -> bool:
    """Imported jobs in which the model found no technical skill at all (sales, recruiting, ...) are kept
    in the database and on the admin page, but not offered to users. Demo and pasted jobs always show,
    and a job that has not been read yet is shown until it has."""
    if job["source"] in ("demo", "manual") or job["extraction"] is None:
        return True
    return bool(job["extraction"].get("skills"))


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
    # "skills" comes from the cached extraction (filled at start); empty until a job has been read.
    return [{k: v for k, v in j.items() if k != "extraction"}
            | {"extracted": j["extraction"] is not None, "image": job_image(j),
               "skills": (j["extraction"] or {}).get("skills", [])}
            for j in state.store.list(source) if is_listed(j)]


@app.get("/jobs/{job_id}")
def jobs_get(job_id: int, lang: str = Depends(get_lang)):
    job = state.store.get(job_id)
    if job is None:
        raise HTTPException(404, msg("job.not_found", lang))
    job["extraction"] = job_extraction(job, lang)
    job["image"] = job_image(job)
    return job


@app.get("/quiz/topics")
def quiz_topics(lang: str = Depends(get_lang)):
    return {"topics": state.quiz.topics(), "names": {t: msg(f"topic.{t}", lang) for t in default_dictionary().topics}}


@app.post("/quiz/start")
def quiz_start(body: QuizStartIn, lang: str = Depends(get_lang)):
    topics = list(body.topics)
    if body.job_id is not None:
        job = state.store.get(body.job_id)
        if job is None:
            raise HTTPException(404, msg("job.not_found", lang))
        d = default_dictionary()
        job_topics = [t for t in dict.fromkeys(d.topic_of(s) for s in job_extraction(job, lang)["skills"]) if t]
        topics += [t for t in job_topics if t in state.quiz.by_topic and t not in topics]
        if not topics:
            raise HTTPException(422, msg("quiz.job_no_topics", lang))
    try:
        return state.quiz.start(topics, body.total, body.level, lang)
    except QuizError as exc:
        raise http_error(422, exc, lang) from exc


@app.post("/quiz/submit")
def quiz_submit(body: QuizSubmitIn, lang: str = Depends(get_lang)):
    try:
        return state.quiz.submit(body.session_id, body.answers)
    except QuizError as exc:
        raise http_error(422, exc, lang) from exc


def _job_skills(job_id: int, lang: str = "en") -> tuple[dict, list[str]]:
    job = state.store.get(job_id)
    if job is None:
        raise HTTPException(404, msg("job.not_found_id", lang, id=job_id))
    return job, job_extraction(job, lang)["skills"]


@app.post("/matches")
def matches(body: MatchIn, lang: str = Depends(get_lang)):
    ids = body.job_ids or [j["id"] for j in state.store.list() if is_listed(j)]
    jobs = []
    for jid in ids:
        job, skills = _job_skills(jid, lang)
        jobs.append({"id": job["id"], "title": job["title"], "company": job["company"], "source": job["source"],
                     "is_demo": job["is_demo"], "url": job["url"], "image": job_image(job), "skills": skills})
    return {"ranking": rank_jobs(jobs, body.cv_skills, body.quiz_scores, lang)}


@app.post("/roadmap")
def roadmap(body: RoadmapIn, lang: str = Depends(get_lang)):
    job, skills = _job_skills(body.job_id, lang)
    result = match_job(skills, body.cv_skills, body.quiz_scores, lang=lang)
    return {"job": {"id": job["id"], "title": job["title"], "company": job["company"]},
            "match": result, "roadmap": build_roadmap(result, body.cv_skills, body.quiz_scores, lang=lang)}


@app.post("/roadmap/pdf")
def roadmap_pdf(body: RoadmapIn, lang: str = Depends(get_lang)):
    """Same inputs as /roadmap; returns a one-page PDF summary to download."""
    from fastapi.responses import Response

    from core.summary import summary_pdf

    job, skills = _job_skills(body.job_id, lang)
    result = match_job(skills, body.cv_skills, body.quiz_scores, lang=lang)
    pdf = summary_pdf(job, result, build_roadmap(result, body.cv_skills, body.quiz_scores, lang=lang), lang)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="skilllens_job{job["id"]}.pdf"'})


@app.get("/results/comparison")
def results_comparison(lang: str = Depends(get_lang)):
    """Measured test-set comparison written by scripts/evaluate.py (404 until it has been run)."""
    import json

    path = ROOT / "results" / "test_metrics.json"
    if not path.exists():
        raise HTTPException(404, msg("results.missing", lang))
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"test_sentences": data["test_sentences"], "device": data["run"]["device"],
            "latency_setup": {k: data["run"]["args"][k] for k in ("latency_sentences", "warmup")},
            "models": {name: {k: m[k] for k in ("scores", "latency", "error_counts", "parameters", "best_val_epoch")}
                       for name, m in data["models"].items()}}


# ------------------------------------------------------------------ admin

def require_admin(x_admin_token: str | None = Header(None), lang: str = Depends(get_lang)) -> None:
    if not x_admin_token or not secrets.compare_digest(x_admin_token, state.admin_token):
        raise HTTPException(401, msg("admin.unauthorized", lang))


@app.get("/admin/api/stats", dependencies=[Depends(require_admin)])
def admin_stats():
    from core.quiz import LEVELS

    jobs = state.store.list()
    by_source: dict[str, int] = {}
    for j in jobs:
        by_source[j["source"]] = by_source.get(j["source"], 0) + 1
    bank = {t: {lv: sum(q["difficulty"] == d for q in qs) for lv, d in LEVELS.items()}
            for t, qs in sorted(state.quiz.by_topic.items())}
    usage = [{"route": r, "count": u["count"], "errors": u["errors"], "avg_ms": u["total_ms"] / u["count"]}
             for r, u in sorted(state.usage.items(), key=lambda kv: -kv[1]["count"])]
    return {"uptime_s": time.time() - state.started, "jobs": len(jobs), "by_source": by_source,
            "extracted": sum(j["extraction"] is not None for j in jobs),
            "hidden": sum(not is_listed(j) for j in jobs),
            "model": state.extractor.model_name if state.extractor else None, "model_error": state.extractor_error,
            "models": sorted(state.models), "quiz_bank": bank,
            "quiz_sessions": len(state.quiz.sessions), "usage": usage,
            "auto_import": {**state.auto_import, "boards": [f"{s}:{b}" for s, b in state.auto_import.get("boards", [])]}
            if state.auto_import else None,
            "embedding": ({"model": state.extractor.embedder.model_name,
                           "threshold": state.extractor.embedder.threshold}
                          if state.extractor is not None and state.extractor.embedder is not None else None)}


@app.get("/admin/api/jobs", dependencies=[Depends(require_admin)])
def admin_jobs():
    return [{k: j[k] for k in ("id", "title", "company", "source", "is_demo", "imported_at", "url")}
            | {"skills": (j["extraction"] or {}).get("skills", []),
               "extracted_by": (j["extraction"] or {}).get("model"), "listed": is_listed(j)}
            for j in state.store.list()]


@app.delete("/admin/api/jobs/{job_id}", dependencies=[Depends(require_admin)])
def admin_delete_job(job_id: int, lang: str = Depends(get_lang)):
    if not state.store.delete(job_id):
        raise HTTPException(404, msg("job.not_found", lang))
    return {"deleted": job_id}


@app.post("/admin/api/jobs/{job_id}/reextract", dependencies=[Depends(require_admin)])
def admin_reextract(job_id: int, lang: str = Depends(get_lang)):
    job = state.store.get(job_id)
    if job is None:
        raise HTTPException(404, msg("job.not_found", lang))
    state.store.clear_extraction(job_id)
    job["extraction"] = None
    t0 = time.perf_counter()
    ex = job_extraction(job, lang)
    return {"id": job_id, "skills": ex["skills"], "mentions": len(ex["mentions"]),
            "ms": (time.perf_counter() - t0) * 1000}


@app.get("/admin/api/imports", dependencies=[Depends(require_admin)])
def admin_imports():
    return state.store.imports()


@app.get("/admin/api/quiz", dependencies=[Depends(require_admin)])
def admin_quiz(topic: str | None = None, level: str | None = None, lang: str = Depends(get_lang)):
    """The question bank with answers (admin only), filtered by topic and level."""
    from core.quiz import LEVELS

    out = []
    for q in state.quiz.bank:
        if (topic and q["topic"] != topic) or (level and q["difficulty"] != LEVELS.get(level)):
            continue
        question, options, explanation = state.quiz._view(q, lang)
        out.append({"id": q["id"], "topic": q["topic"], "level": {v: k for k, v in LEVELS.items()}[q["difficulty"]],
                    "question": question, "options": options, "answer": q["answer"], "explanation": explanation})
    return out


# ------------------------------------------------------------------ frontend

WEB = ROOT / "web"
if WEB.exists():
    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        # no-cache: the page links versioned CSS/JS, so a fresh page always pulls the current assets
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse(WEB / "admin.html", headers={"Cache-Control": "no-cache"})

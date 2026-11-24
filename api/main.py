"""SkillLens FastAPI application. The web frontend (web/) is served by the same app.

Run (development, auto-reload):   fastapi dev main.py
Run (plain):                      python -m uvicorn api.main:app --port 8000
API documentation:                /docs (Swagger UI) and /redoc

Code layout:
  api/main.py         this file: app, lifespan, middleware, routers, static files
  api/state.py        shared state and dependencies (language, DB session, admin check, model)
  api/security.py     password hashing (Argon2) and JWT sign-in tokens
  api/schemas.py      request/response models
  api/routers/*.py    endpoints by area (auth, users, jobs, cv, skills, quiz, matching, admin, system)
  core/db.py          SQLModel tables

Config (environment variables):
  SKILLLENS_MODEL       distilbert | bilstm           (default distilbert)
  SKILLLENS_CHECKPOINT  path to the checkpoint dir     (default checkpoints/<model>)
  SKILLLENS_DB          SQLite database file           (default data/jobs.db)
  SKILLLENS_DEVICE      auto | cpu | cuda | mps         (default auto)
  SKILLLENS_ADMIN_TOKEN token for /admin                (default: random, written to runs/admin_token.txt)
  SKILLLENS_JWT_SECRET  secret for sign-in tokens       (default: random, kept in runs/jwt_secret.txt)
  SKILLLENS_CORS        comma-separated origins allowed to call the API from a browser (default: none)
  SKILLLENS_AUTO_IMPORT boards imported on a schedule, e.g. "greenhouse:gitlab,lever:acme" (default: none)
  SKILLLENS_IMPORT_HOURS hours between scheduled imports (default 24; the first round runs at start)
  SKILLLENS_LIGHT       1 = light mode: no model is loaded; jobs show the model results saved in the database
  SKILLLENS_EMBED       0 turns the Sentence-BERT fallback for unmatched spans off (default on)
  SKILLLENS_EMBED_THRESHOLD cosine similarity needed for that fallback (default 0.75)
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from core.jobs import JobStore, demo_jobs  # noqa: E402
from core.quiz import QuizEngine  # noqa: E402

from .routers import admin, auth, cv, jobs, matching, quiz, skills, system, users  # noqa: E402
from .state import (auto_import_loop, is_listed, load_extractor, parse_auto_import,  # noqa: E402,F401
                    run_scheduled_imports, setup_secrets, state, warm_extractions)


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.store = JobStore(os.environ.get("SKILLLENS_DB", ROOT / "data" / "jobs.db"))
    for job in demo_jobs():  # demo listings are always available offline
        state.store.upsert(job)
    state.quiz = QuizEngine()
    state.started, state.usage = time.time(), {}
    setup_secrets()
    state.light = os.environ.get("SKILLLENS_LIGHT") == "1"
    if state.light:  # no model, no PyTorch: saved model results are served (fast start for demos)
        state.extractor, state.extractor_error, state.models = None, None, {}
    elif os.environ.get("SKILLLENS_SKIP_MODEL") != "1":
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


TAGS = [
    {"name": "auth", "description": "Create an account and sign in (OAuth2 password flow, JWT bearer token)."},
    {"name": "users", "description": "The signed-in user's account and saved data. Needs a bearer token."},
    {"name": "jobs", "description": "Job catalog: list, search, import, and CRUD for jobs you created."},
    {"name": "cv", "description": "CV analysis (PDF or text). Nothing is stored."},
    {"name": "skills", "description": "Skill dictionary and the trained taggers (BiLSTM, DistilBERT)."},
    {"name": "quiz", "description": "Topic quiz at junior, mid or senior level."},
    {"name": "matching", "description": "Job matching from CV and quiz evidence, learning roadmap, PDF summary."},
    {"name": "admin", "description": "Admin API; needs the X-Admin-Token header."},
    {"name": "system", "description": "Health and measured model results."},
]

app = FastAPI(
    title="SkillLens API",
    version="1.0.0",
    summary="Developer skill assessment and job matching.",
    description="Reads job ads with a fine-tuned DistilBERT model, compares them with a CV and a short quiz, "
                "and builds a learning roadmap. Click **Authorize** to sign in with an account from `/auth/register`.",
    openapi_tags=TAGS,
    lifespan=lifespan,
)

origins = [o.strip() for o in os.environ.get("SKILLLENS_CORS", "").split(",") if o.strip()]
if origins:
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"],
                       expose_headers=["X-Total-Count"])


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


for module in (auth, users, jobs, cv, skills, quiz, matching, admin, system):
    app.include_router(module.router)


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

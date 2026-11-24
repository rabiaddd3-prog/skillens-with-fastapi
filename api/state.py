"""Shared application state and dependencies used by every router.

Kept apart from api/main.py so routers can import it without a circular import.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from pathlib import Path

from fastapi import Depends, Header, HTTPException

from core.i18n import LocalizedError, msg, norm_lang
from core.jobs import JobImportError, JobStore, fetch_greenhouse, fetch_lever
from core.quiz import QuizEngine

ROOT = Path(__file__).resolve().parents[1]


class State:
    extractor = None
    extractor_error: str | None = None
    # Both models, for the live side-by-side comparison; a missing checkpoint just leaves a gap.
    models: dict = {}
    store: JobStore | None = None
    quiz: QuizEngine | None = None
    admin_token: str = ""
    jwt_secret: str = ""
    started: float = 0.0
    usage: dict = {}   # route -> {"count", "errors", "total_ms"}; in memory, reset on restart
    auto_import: dict = {}  # {"boards": [(source, board)], "every_hours", "last_run", "next_run"}


state = State()


# ------------------------------------------------------------------ dependencies

def get_lang(x_lang: str | None = Header(None, description="Language of messages: en or tr")) -> str:
    """Language of user-facing texts, sent by the frontend as the X-Lang header (en | tr)."""
    return norm_lang(x_lang)


def get_session():
    """One database session per request (SQLModel)."""
    with state.store.session() as session:
        yield session


def http_error(status: int, exc: LocalizedError, lang: str) -> HTTPException:
    return HTTPException(status, exc.localized(lang))


def require_admin(x_admin_token: str | None = Header(None), lang: str = Depends(get_lang)) -> None:
    if not x_admin_token or not secrets.compare_digest(x_admin_token, state.admin_token):
        raise HTTPException(401, msg("admin.unauthorized", lang))


# ------------------------------------------------------------------ secrets

def _secret_from(env: str, file: str, nbytes: int, announce: str | None = None) -> str:
    value = os.environ.get(env)
    if value:
        return value
    path = ROOT / "runs" / file
    if file == "jwt_secret.txt" and path.exists():  # keep sign-ins valid across restarts
        return path.read_text(encoding="utf-8").strip()
    value = secrets.token_urlsafe(nbytes)
    path.parent.mkdir(exist_ok=True)
    path.write_text(value + "\n", encoding="utf-8")
    if announce:
        print(f"{announce} (also in {path}): {value}", flush=True)
    return value


def setup_secrets() -> None:
    state.admin_token = _secret_from("SKILLLENS_ADMIN_TOKEN", "admin_token.txt", 12, "SkillLens admin token")
    state.jwt_secret = _secret_from("SKILLLENS_JWT_SECRET", "jwt_secret.txt", 32)


# ------------------------------------------------------------------ model

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


def warm_extractions() -> None:
    """Extract every job once at start, so the job cards can show their skills straight away."""
    for job in state.store.list():
        try:
            job_extraction(job)
        except Exception:  # noqa: BLE001 - a bad job must not stop the server
            pass


# ------------------------------------------------------------------ jobs

def is_listed(job: dict) -> bool:
    """Imported jobs in which the model found no technical skill at all (sales, recruiting, ...) are kept
    in the database and on the admin page, but not offered to users. Demo and pasted jobs always show,
    and a job that has not been read yet is shown until it has."""
    if job["source"] in ("demo", "manual") or job["extraction"] is None:
        return True
    return bool(job["extraction"].get("skills"))


def job_image(job: dict) -> dict | None:
    """Representative stock photo for a demo job (data/job_images.json), with its credit."""
    path = ROOT / "data" / "job_images.json"
    if job["source"] != "demo" or not path.exists():
        return None
    entry = json.loads(path.read_text(encoding="utf-8")).get("images", {}).get(job["source_id"])
    if not entry or not (ROOT / "web" / "img" / "jobs" / entry["file"]).exists():
        return None
    return {"url": f"/static/img/jobs/{entry['file']}", "alt": entry["alt"], "photographer": entry["photographer"],
            "source": entry["source"], "page_url": entry["page_url"]}


def job_or_404(job_id: int, lang: str = "en") -> dict:
    job = state.store.get(job_id)
    if job is None:
        raise HTTPException(404, msg("job.not_found_id", lang, id=job_id))
    return job


def job_skills(job_id: int, lang: str = "en") -> tuple[dict, list[str]]:
    job = job_or_404(job_id, lang)
    return job, job_extraction(job, lang)["skills"]


# ------------------------------------------------------------------ imports

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

"""Admin API (header X-Admin-Token): overview, job catalog, import log, question bank, users."""
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from core.db import QuizResult, User
from core.i18n import msg
from core.quiz import LEVELS

from ..state import get_lang, get_session, is_listed, job_extraction, require_admin, state

router = APIRouter(prefix="/admin/api", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/stats", summary="Overview: model, jobs, question bank, API usage")
def admin_stats(session: Session = Depends(get_session)):
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
            "users": session.exec(select(func.count()).select_from(User)).one(),
            "quiz_results": session.exec(select(func.count()).select_from(QuizResult)).one(),
            "model": state.extractor.model_name if state.extractor else None, "model_error": state.extractor_error,
            "models": sorted(state.models), "quiz_bank": bank,
            "quiz_sessions": len(state.quiz.sessions), "usage": usage,
            "auto_import": {**state.auto_import, "boards": [f"{s}:{b}" for s, b in state.auto_import.get("boards", [])]}
            if state.auto_import else None,
            "embedding": ({"model": state.extractor.embedder.model_name,
                           "threshold": state.extractor.embedder.threshold}
                          if state.extractor is not None and state.extractor.embedder is not None else None)}


@router.get("/jobs", summary="Every job, including hidden ones")
def admin_jobs():
    return [{k: j[k] for k in ("id", "title", "company", "source", "is_demo", "imported_at", "url", "owner_id")}
            | {"skills": (j["extraction"] or {}).get("skills", []),
               "extracted_by": (j["extraction"] or {}).get("model"), "listed": is_listed(j)}
            for j in state.store.list()]


@router.delete("/jobs/{job_id}", summary="Delete any job")
def admin_delete_job(job_id: int, lang: str = Depends(get_lang)):
    if not state.store.delete(job_id):
        raise HTTPException(404, msg("job.not_found", lang))
    return {"deleted": job_id}


@router.post("/jobs/{job_id}/reextract", summary="Run the model on a job again")
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


@router.get("/imports", summary="Import log, newest first")
def admin_imports():
    return state.store.imports()


@router.get("/users", summary="Registered users (no password hashes)")
def admin_users(session: Session = Depends(get_session)):
    return [{"id": u.id, "email": u.email, "name": u.name, "created_at": u.created_at}
            for u in session.exec(select(User).order_by(User.id))]


@router.get("/quiz", summary="The question bank with answers")
def admin_quiz(topic: str | None = None, level: str | None = None, lang: str = Depends(get_lang)):
    out = []
    for q in state.quiz.bank:
        if (topic and q["topic"] != topic) or (level and q["difficulty"] != LEVELS.get(level)):
            continue
        question, options, explanation = state.quiz._view(q, lang)
        out.append({"id": q["id"], "topic": q["topic"], "level": {v: k for k, v in LEVELS.items()}[q["difficulty"]],
                    "question": question, "options": options, "answer": q["answer"], "explanation": explanation})
    return out

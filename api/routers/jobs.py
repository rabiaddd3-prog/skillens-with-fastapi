"""Job catalog: list, read, import, and create / update / delete for signed-in users.

Demo and imported jobs are read-only through this API (the admin API can delete them); a job created
with POST /jobs belongs to its creator, and only the creator can change or delete it.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from core.db import User
from core.i18n import LocalizedError, msg
from core.jobs import JobImportError, manual_job

from ..schemas import JobCreate, JobIn, JobPatch, JobSummary, JobUpdate
from ..security import get_current_user
from ..state import get_lang, http_error, import_board, is_listed, job_extraction, job_image, job_or_404, state

router = APIRouter(prefix="/jobs", tags=["jobs"])


def summary(j: dict) -> dict:
    # "skills" comes from the cached extraction (filled at start); empty until a job has been read.
    return {k: v for k, v in j.items() if k != "extraction"} | {
        "extracted": j["extraction"] is not None, "image": job_image(j),
        "skills": (j["extraction"] or {}).get("skills", [])}


@router.get("", response_model=list[JobSummary], summary="List jobs (filter, search, paginate)")
def jobs_list(response: Response,
              source: str | None = Query(None, description="demo, manual, greenhouse or lever"),
              q: str | None = Query(None, description="search in title, company and skills"),
              skill: str | None = Query(None, description="only jobs that ask for this canonical skill"),
              skip: int = Query(0, ge=0), limit: int | None = Query(None, ge=1, le=200)):
    """Jobs offered to users (imported jobs with no technical skill are hidden). The total before
    pagination is in the `X-Total-Count` header."""
    items = [summary(j) for j in state.store.list(source) if is_listed(j)]
    if q:
        ql = q.lower()
        items = [j for j in items if ql in f"{j['title']} {j['company'] or ''} {' '.join(j['skills'])}".lower()]
    if skill:
        items = [j for j in items if skill.lower() in (s.lower() for s in j["skills"])]
    response.headers["X-Total-Count"] = str(len(items))
    return items[skip: skip + limit if limit else None]


@router.get("/{job_id}", summary="One job with the model's extracted requirements")
def jobs_get(job_id: int, lang: str = Depends(get_lang)):
    job = job_or_404(job_id, lang)
    job["extraction"] = job_extraction(job, lang)
    job["image"] = job_image(job)
    return job


@router.post("", response_model=JobSummary, status_code=status.HTTP_201_CREATED,
             summary="Create a job (signed-in users)")
def jobs_create(body: JobCreate, user: User = Depends(get_current_user)):
    jid, _ = state.store.upsert({"source": "manual", "source_id": f"user{user.id}:{uuid.uuid4().hex[:12]}",
                                 "owner_id": user.id, **body.model_dump()})
    return summary(state.store.get(jid))


def _own_job(job_id: int, user: User, lang: str) -> dict:
    job = job_or_404(job_id, lang)
    if job["owner_id"] != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, msg("job.not_owner", lang))
    return job


@router.put("/{job_id}", response_model=JobSummary, summary="Replace a job you created")
def jobs_replace(job_id: int, body: JobUpdate, user: User = Depends(get_current_user),
                 lang: str = Depends(get_lang)):
    _own_job(job_id, user, lang)
    return summary(state.store.update(job_id, body.model_dump()))


@router.patch("/{job_id}", response_model=JobSummary, summary="Change some fields of a job you created")
def jobs_patch(job_id: int, body: JobPatch, user: User = Depends(get_current_user),
               lang: str = Depends(get_lang)):
    _own_job(job_id, user, lang)
    return summary(state.store.update(job_id, body.model_dump(exclude_unset=True)))


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a job you created")
def jobs_delete(job_id: int, user: User = Depends(get_current_user), lang: str = Depends(get_lang)):
    _own_job(job_id, user, lang)
    state.store.delete(job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/import", summary="Paste an ad, or import a Greenhouse / Lever board")
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

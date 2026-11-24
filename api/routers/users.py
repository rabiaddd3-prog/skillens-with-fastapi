"""The signed-in user's account and saved data: CV skills, quiz results, roadmap progress, saved jobs.

Every endpoint here needs `Authorization: Bearer <token>` and only touches the caller's own rows.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, delete, select

from core.db import Job, Profile, QuizResult, RoadmapProgress, SavedJob, User, utcnow
from core.i18n import msg
from core.skills import default_dictionary

from ..schemas import (ProfileIn, ProfileRead, ProgressIn, ProgressRead, QuizResultIn, QuizResultRead, SavedJobIn,
                       SavedJobRead, UserPatch, UserRead)
from ..security import get_current_user, hash_password
from ..state import get_lang, get_session

router = APIRouter(prefix="/users/me", tags=["users"])


# ------------------------------------------------------------------ account

@router.get("", response_model=UserRead, summary="The signed-in user")
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("", response_model=UserRead, summary="Change name or password")
def update_me(body: UserPatch, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    if body.name is not None:
        user.name = body.name.strip()
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Delete the account and all its data")
def delete_me(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    for table in (Profile, QuizResult, RoadmapProgress, SavedJob):
        session.exec(delete(table).where(table.user_id == user.id))
    for job in session.exec(select(Job).where(Job.owner_id == user.id)):  # created jobs stay, without an owner
        job.owner_id = None
        session.add(job)
    session.delete(user)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ CV profile

@router.get("/profile", response_model=ProfileRead, summary="Saved CV skills")
def get_profile(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    p = session.get(Profile, user.id)
    return ProfileRead(cv_skills=json.loads(p.cv_skills) if p else [], updated_at=p.updated_at if p else None)


@router.put("/profile", response_model=ProfileRead, summary="Save the confirmed CV skills")
def put_profile(body: ProfileIn, user: User = Depends(get_current_user), session: Session = Depends(get_session),
                lang: str = Depends(get_lang)):
    d = default_dictionary()
    unknown = [s for s in body.cv_skills if s not in d.skills]
    if unknown:  # only canonical names, the same ones the matcher uses
        raise HTTPException(422, msg("profile.unknown_skills", lang, skills=", ".join(unknown)))
    p = session.get(Profile, user.id) or Profile(user_id=user.id)
    p.cv_skills, p.updated_at = json.dumps(list(dict.fromkeys(body.cv_skills))), utcnow()
    session.add(p)
    session.commit()
    return ProfileRead(cv_skills=json.loads(p.cv_skills), updated_at=p.updated_at)


# ------------------------------------------------------------------ quiz results

def _quiz_read(r: QuizResult) -> QuizResultRead:
    return QuizResultRead(id=r.id, taken_at=r.taken_at, level=r.level, correct=r.correct, total=r.total,
                          scores=json.loads(r.scores))


@router.get("/quiz-results", response_model=list[QuizResultRead], summary="Finished quizzes, oldest first")
def list_quiz_results(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    rows = session.exec(select(QuizResult).where(QuizResult.user_id == user.id).order_by(QuizResult.id))
    return [_quiz_read(r) for r in rows]


@router.post("/quiz-results", response_model=QuizResultRead, status_code=status.HTTP_201_CREATED,
             summary="Save a finished quiz")
def add_quiz_result(body: QuizResultIn, user: User = Depends(get_current_user),
                    session: Session = Depends(get_session), lang: str = Depends(get_lang)):
    if body.correct > body.total:
        raise HTTPException(422, msg("quiz.bad_result", lang))
    r = QuizResult(user_id=user.id, level=body.level, correct=body.correct, total=body.total,
                   scores=json.dumps(body.scores))
    session.add(r)
    session.commit()
    session.refresh(r)
    return _quiz_read(r)


@router.delete("/quiz-results/{result_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete one quiz result")
def delete_quiz_result(result_id: int, user: User = Depends(get_current_user),
                       session: Session = Depends(get_session), lang: str = Depends(get_lang)):
    r = session.get(QuizResult, result_id)
    if r is None or r.user_id != user.id:  # someone else's result looks the same as a missing one
        raise HTTPException(404, msg("not_found", lang))
    session.delete(r)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ roadmap progress

@router.get("/roadmaps", response_model=list[ProgressRead], summary="Roadmap progress for every job")
def list_progress(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    rows = session.exec(select(RoadmapProgress).where(RoadmapProgress.user_id == user.id))
    return [ProgressRead(job_id=r.job_id, done=json.loads(r.done), updated_at=r.updated_at) for r in rows]


@router.get("/roadmaps/{job_id}", response_model=ProgressRead, summary="Ticked steps of one roadmap")
def get_progress(job_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    r = session.exec(select(RoadmapProgress).where(RoadmapProgress.user_id == user.id,
                                                   RoadmapProgress.job_id == job_id)).first()
    return ProgressRead(job_id=job_id, done=json.loads(r.done) if r else [], updated_at=r.updated_at if r else None)


@router.put("/roadmaps/{job_id}", response_model=ProgressRead, summary="Save the ticked steps of one roadmap")
def put_progress(job_id: int, body: ProgressIn, user: User = Depends(get_current_user),
                 session: Session = Depends(get_session)):
    r = session.exec(select(RoadmapProgress).where(RoadmapProgress.user_id == user.id,
                                                   RoadmapProgress.job_id == job_id)).first()
    r = r or RoadmapProgress(user_id=user.id, job_id=job_id)
    r.done, r.updated_at = json.dumps(list(dict.fromkeys(body.done))), utcnow()
    session.add(r)
    session.commit()
    return ProgressRead(job_id=job_id, done=json.loads(r.done), updated_at=r.updated_at)


# ------------------------------------------------------------------ saved jobs

def _saved_read(s: SavedJob, job: Job) -> SavedJobRead:
    return SavedJobRead(id=s.id, job_id=s.job_id, title=job.title, company=job.company, note=s.note, saved_at=s.saved_at)


@router.get("/saved-jobs", response_model=list[SavedJobRead], summary="Bookmarked jobs")
def list_saved(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    rows = session.exec(select(SavedJob, Job).join(Job, SavedJob.job_id == Job.id)
                        .where(SavedJob.user_id == user.id).order_by(SavedJob.id))
    return [_saved_read(s, j) for s, j in rows]


@router.post("/saved-jobs", response_model=SavedJobRead, status_code=status.HTTP_201_CREATED,
             summary="Bookmark a job")
def add_saved(body: SavedJobIn, user: User = Depends(get_current_user), session: Session = Depends(get_session),
              lang: str = Depends(get_lang)):
    job = session.get(Job, body.job_id)
    if job is None:
        raise HTTPException(404, msg("job.not_found_id", lang, id=body.job_id))
    if session.exec(select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_id == body.job_id)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, msg("saved.exists", lang))
    s = SavedJob(user_id=user.id, job_id=body.job_id, note=body.note)
    session.add(s)
    session.commit()
    session.refresh(s)
    return _saved_read(s, job)


@router.delete("/saved-jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a bookmark")
def delete_saved(job_id: int, user: User = Depends(get_current_user), session: Session = Depends(get_session),
                 lang: str = Depends(get_lang)):
    s = session.exec(select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_id == job_id)).first()
    if s is None:
        raise HTTPException(404, msg("not_found", lang))
    session.delete(s)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

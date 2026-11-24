"""Topic quiz: answers stay on the server until the quiz is submitted."""
from fastapi import APIRouter, Depends, HTTPException

from core.i18n import msg
from core.quiz import QuizError
from core.skills import default_dictionary

from ..schemas import QuizStartIn, QuizSubmitIn
from ..state import get_lang, http_error, job_extraction, state

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.get("/topics", summary="Quiz topics and question counts")
def quiz_topics(lang: str = Depends(get_lang)):
    return {"topics": state.quiz.topics(), "names": {t: msg(f"topic.{t}", lang) for t in default_dictionary().topics}}


@router.post("/start", summary="Start a quiz on topics or on a job's topics")
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


@router.post("/submit", summary="Submit answers; returns scores per topic and the answer key")
def quiz_submit(body: QuizSubmitIn, lang: str = Depends(get_lang)):
    try:
        return state.quiz.submit(body.session_id, body.answers)
    except QuizError as exc:
        raise http_error(422, exc, lang) from exc

"""Job matching and the learning roadmap."""
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from core.matching import match_job, rank_jobs
from core.roadmap import build_roadmap

from ..schemas import MatchIn, RoadmapIn
from ..state import get_lang, is_listed, job_image, job_skills, state

router = APIRouter(tags=["matching"])


@router.post("/matches", summary="Rank jobs by CV coverage and quiz performance")
def matches(body: MatchIn, lang: str = Depends(get_lang)):
    ids = body.job_ids or [j["id"] for j in state.store.list() if is_listed(j)]
    jobs = []
    for jid in ids:
        job, skills = job_skills(jid, lang)
        jobs.append({"id": job["id"], "title": job["title"], "company": job["company"], "source": job["source"],
                     "is_demo": job["is_demo"], "url": job["url"], "image": job_image(job), "skills": skills})
    return {"ranking": rank_jobs(jobs, body.cv_skills, body.quiz_scores, lang)}


@router.post("/roadmap", summary="Ordered learning steps with prerequisites and courses")
def roadmap(body: RoadmapIn, lang: str = Depends(get_lang)):
    job, skills = job_skills(body.job_id, lang)
    result = match_job(skills, body.cv_skills, body.quiz_scores, lang=lang)
    return {"job": {"id": job["id"], "title": job["title"], "company": job["company"]},
            "match": result, "roadmap": build_roadmap(result, body.cv_skills, body.quiz_scores, lang=lang)}


@router.post("/roadmap/pdf", summary="The same roadmap as a PDF summary",
             responses={200: {"content": {"application/pdf": {}}}})
def roadmap_pdf(body: RoadmapIn, lang: str = Depends(get_lang)):
    from core.summary import summary_pdf

    job, skills = job_skills(body.job_id, lang)
    result = match_job(skills, body.cv_skills, body.quiz_scores, lang=lang)
    pdf = summary_pdf(job, result, build_roadmap(result, body.cv_skills, body.quiz_scores, lang=lang), lang)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="skilllens_job{job["id"]}.pdf"'})

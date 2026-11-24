"""CV analysis. Nothing is stored; a signed-in user saves the confirmed skills via /users/me/profile."""
from fastapi import APIRouter, Depends, File, UploadFile

from core.cv import MAX_PDF_BYTES, CVError, detect_skills, pdf_to_text

from ..schemas import TextIn
from ..state import get_lang, http_error

router = APIRouter(prefix="/cv", tags=["cv"])


@router.post("/analyze", summary="Text-based PDF upload -> candidate skills")
async def cv_analyze(file: UploadFile = File(...), lang: str = Depends(get_lang)):
    """For scanned CVs use /cv/analyze-text."""
    try:
        cv_text = pdf_to_text(await file.read(MAX_PDF_BYTES + 1))
        return {"skills": detect_skills(cv_text), "characters": len(cv_text)}
    except CVError as exc:
        raise http_error(422, exc, lang) from exc


@router.post("/analyze-text", summary="Pasted CV text -> candidate skills")
def cv_analyze_text(body: TextIn, lang: str = Depends(get_lang)):
    try:
        return {"skills": detect_skills(body.text), "characters": len(body.text)}
    except CVError as exc:
        raise http_error(422, exc, lang) from exc

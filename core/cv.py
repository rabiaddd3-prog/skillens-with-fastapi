"""CV text extraction and dictionary-based skill detection.

The job-ad model is not used for CV scoring: it was trained and evaluated on job
ads only, so CV skills come from the dictionary and the user confirms them.
Nothing is written to disk; the CV only lives in the request.
"""
from __future__ import annotations

from .i18n import LocalizedError
from .skills import SkillDictionary, default_dictionary

MAX_PDF_BYTES = 5 * 1024 * 1024
MIN_TEXT_CHARS = 30


class CVError(LocalizedError):
    """User-facing problem with an uploaded CV (message is safe to show)."""


def pdf_to_text(data: bytes, max_bytes: int = MAX_PDF_BYTES) -> str:
    import pymupdf

    if not data:
        raise CVError("cv.empty_file")
    if len(data) > max_bytes:
        raise CVError("cv.too_large", mb=max_bytes // (1024 * 1024))
    if not data.startswith(b"%PDF"):
        raise CVError("cv.not_pdf")
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            text = "\n".join(page.get_text() for page in doc)
    except Exception as exc:  # pymupdf raises several internal error types for broken files
        raise CVError("cv.damaged") from exc
    if len(text.strip()) < MIN_TEXT_CHARS:
        raise CVError("cv.no_text")
    return text


def detect_skills(text: str, dictionary: SkillDictionary | None = None) -> list[dict]:
    """Candidate skills with the snippets that triggered them, for the user to confirm."""
    dictionary = dictionary or default_dictionary()
    if not text or not text.strip():
        raise CVError("cv.empty_text")
    found: dict[str, dict] = {}
    for m in dictionary.find(text):
        item = found.setdefault(m.skill, {"skill": m.skill, "evidence": [], "topic": dictionary.topic_of(m.skill)})
        if len(item["evidence"]) < 3:
            a, b = max(0, m.start - 40), min(len(text), m.end + 40)
            item["evidence"].append(" ".join(text[a:b].split()))
    return list(found.values())

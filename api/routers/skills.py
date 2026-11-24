"""Skill dictionary and the trained taggers."""
import time

from fastapi import APIRouter, Depends, HTTPException

from core.i18n import msg
from core.skills import default_dictionary

from ..schemas import TextIn
from ..state import cached_text_extraction, extractor, get_lang, state

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("/dictionary", summary="Canonical skills, aliases and quiz topics")
def skills_dictionary(lang: str = Depends(get_lang)):
    d = default_dictionary()
    return {"topics": {t: msg(f"topic.{t}", lang) for t in d.topics},
            "skills": [{"name": s.name, "category": s.category, "topic": s.topic, "aliases": d.aliases.get(s.name, [])}
                       for s in d.skills.values()]}


@router.post("/extract", summary="English text -> Skill/Knowledge spans with character offsets")
def skills_extract(body: TextIn, lang: str = Depends(get_lang)):
    if state.light and state.extractor is None:  # light mode: only texts whose model output was saved
        saved = cached_text_extraction(body.text)
        if saved is not None:
            return saved
    return extractor(lang).extract(body.text)


@router.post("/compare", summary="The same text through BiLSTM and DistilBERT")
def skills_compare(body: TextIn, lang: str = Depends(get_lang)):
    """Model output only (no dictionary fallback): each model's spans, its server-side time, and the
    spans only one model found."""
    if state.light:
        raise HTTPException(503, msg("model.light", lang))
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

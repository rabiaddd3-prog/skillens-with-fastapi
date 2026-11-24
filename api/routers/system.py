"""Health check and the measured model comparison."""
import json

from fastapi import APIRouter, Depends, HTTPException

from core.i18n import msg

from ..state import ROOT, get_lang, is_listed, state

router = APIRouter(tags=["system"])


@router.get("/health", summary="API and model status")
def health():
    return {"status": "ok", "model_loaded": state.extractor is not None, "models": sorted(state.models),
            "model": state.extractor.model_name if state.extractor else None, "model_error": state.extractor_error,
            "jobs": sum(is_listed(j) for j in state.store.list()), "quiz_topics": state.quiz.topics()}


@router.get("/results/comparison", summary="Measured BiLSTM vs DistilBERT test results")
def results_comparison(lang: str = Depends(get_lang)):
    """Written by scripts/evaluate.py (404 until it has been run)."""
    path = ROOT / "results" / "test_metrics.json"
    if not path.exists():
        raise HTTPException(404, msg("results.missing", lang))
    data = json.loads(path.read_text(encoding="utf-8"))
    return {"test_sentences": data["test_sentences"], "device": data["run"]["device"],
            "latency_setup": {k: data["run"]["args"][k] for k in ("latency_sentences", "warmup")},
            "models": {name: {k: m[k] for k in ("scores", "latency", "error_counts", "parameters", "best_val_epoch")}
                       for name, m in data["models"].items()}}

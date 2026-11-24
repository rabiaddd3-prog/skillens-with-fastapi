"""Save the real model's output for the fixed texts of the interface, for light mode.

In light mode (SKILLLENS_LIGHT=1) no model is loaded. Jobs use the extractions already saved in the
database; this file covers the remaining fixed texts (the home page sample sentence), so the home
page still shows the model's highlights. Run again after retraining or changing the texts.

Usage: python scripts/cache_extractions.py
Writes data/cached_extractions.json.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Keep in sync with HOME_SAMPLE in web/app.js.
TEXTS = [
    "You will design scalable REST APIs in Python, write unit tests and work with PostgreSQL and Docker.",
]


def main():
    from core.embed_normalize import load_default
    from core.extractor import SkillExtractor
    from core.utils import pick_device

    device = pick_device("auto")
    ex = SkillExtractor.from_checkpoint(ROOT / "checkpoints" / "distilbert", "distilbert", device)
    ex.embedder = load_default(device=str(device))
    items = {hashlib.sha1(t.encode("utf-8")).hexdigest(): ex.extract(t) for t in TEXTS}
    out = ROOT / "data" / "cached_extractions.json"
    out.write_text(json.dumps({"_about": "Saved DistilBERT output for fixed interface texts (light mode). "
                                         "Written by scripts/cache_extractions.py.", "items": items},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    for t, e in zip(TEXTS, items.values()):
        print(f"{len(e['mentions'])} spans, skills {e['skills']}: {t[:60]}")
    print(f"written {out}")


if __name__ == "__main__":
    main()

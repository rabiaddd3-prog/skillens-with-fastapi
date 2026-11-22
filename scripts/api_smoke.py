"""Start the API in-process with the real checkpoint and run the brief's demo flow once.

Usage: python scripts/api_smoke.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("SKILLLENS_DB", str(ROOT / "runs" / "api_smoke.db"))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

with TestClient(app) as c:
    health = c.get("/health").json()
    print("health:", {k: health[k] for k in ("model_loaded", "model", "model_error", "jobs")})
    job = c.get("/jobs/1").json()
    ex = job["extraction"]
    print(f"\njob 1: {job['title']}")
    for r in ex["requirements"]:
        print(f"  [{r['type']:9s} {r['found_by']:10s}] {r['text']!r} -> {r['normalized']}")
    print("  skills:", ex["skills"])
    quiz = {"python": {"correct": 9, "total": 10, "ratio": 0.9}, "sql": {"correct": 3, "total": 10, "ratio": 0.3}}
    rm = c.post("/roadmap", json={"job_id": 1, "cv_skills": ["Python", "Git"], "quiz_scores": quiz}).json()
    print("\nscores:", {k: (round(v, 3) if v is not None else None) for k, v in rm["match"]["scores"].items()})
    for s in rm["match"]["skills"]:
        print(f"  {s['skill']:10s} {s['status']:12s} quiz={s['quiz_state']}")
    print("roadmap:", [(s["title"], s["reason"]) for s in rm["roadmap"]["steps"]])

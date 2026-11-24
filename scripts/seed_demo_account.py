"""Create (or reset) a demo account for presentations.

The account is clearly a demo ("Demo User", demo@example.com). Its data is made up for the demo:
confirmed CV skills, two finished quizzes (junior, then mid) and two saved jobs, so signing in shows
filled-in screens straight away. Running the script again resets the account to this state.

Usage: python scripts/seed_demo_account.py [--db data/jobs.db] [--password ...]
The password is printed and written to runs/demo_account.txt (not in git). Without --password a new
random one is made each time.
"""
import argparse
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlmodel import delete, select  # noqa: E402

from core.db import Profile, QuizResult, RoadmapProgress, SavedJob, User  # noqa: E402
from core.jobs import DEFAULT_DB, JobStore, demo_jobs  # noqa: E402

EMAIL = "demo@example.com"
CV_SKILLS = ["Python", "SQL", "Git", "Docker", "REST APIs", "FastAPI"]
QUIZZES = [  # (level, {topic: (correct, total)})
    ("junior", {"python": (4, 5), "sql": (2, 5)}),
    ("mid", {"python": (8, 10), "sql": (5, 10), "algorithms": (3, 5)}),
]
SAVED_TITLES = ["Junior Backend Developer (Python)", "DevOps Engineer"]


def main():
    from api.security import hash_password

    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--password", default=None)
    args = p.parse_args()
    password = args.password or f"skilllens-demo-{secrets.token_hex(3)}"

    store = JobStore(args.db)
    for job in demo_jobs():  # the saved jobs below are demo jobs
        store.upsert(job)
    with store.session() as s:
        user = s.exec(select(User).where(User.email == EMAIL)).first()
        if user is None:
            user = User(email=EMAIL, name="Demo User", password_hash=hash_password(password))
        else:
            user.password_hash = hash_password(password)
            for table in (Profile, QuizResult, RoadmapProgress, SavedJob):
                s.exec(delete(table).where(table.user_id == user.id))
        s.add(user)
        s.commit()
        s.refresh(user)

        s.add(Profile(user_id=user.id, cv_skills=json.dumps(CV_SKILLS)))
        for level, topics in QUIZZES:
            scores = {t: {"correct": c, "total": n, "ratio": c / n} for t, (c, n) in topics.items()}
            s.add(QuizResult(user_id=user.id, level=level, correct=sum(c for c, _ in topics.values()),
                             total=sum(n for _, n in topics.values()), scores=json.dumps(scores)))
        jobs = {j["title"]: j["id"] for j in store.list("demo")}
        for title in SAVED_TITLES:
            if title in jobs:
                s.add(SavedJob(user_id=user.id, job_id=jobs[title], note="demo"))
        s.commit()

    print(f"Demo account ready in {args.db}")
    print(f"  e-mail:   {EMAIL}\n  password: {password}")
    if Path(args.db).resolve() == Path(DEFAULT_DB).resolve():  # only the app's own database, not test copies
        out = ROOT / "runs" / "demo_account.txt"
        out.parent.mkdir(exist_ok=True)
        out.write_text(f"e-mail:   {EMAIL}\npassword: {password}\n", encoding="utf-8")
        print(f"(also in {out})")


if __name__ == "__main__":
    main()

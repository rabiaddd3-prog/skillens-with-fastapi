"""Database tables (SQLModel on SQLite).

Tables:
  jobs              job catalog (demo, pasted, Greenhouse, Lever); owner_id is set for jobs a user created
  import_log        every import attempt (admin page)
  users             accounts (password stored as an Argon2 hash)
  profiles          a user's confirmed CV skills
  quiz_results      finished quizzes of a user
  roadmap_progress  ticked roadmap steps per user and job
  saved_jobs        jobs a user bookmarked

The jobs and import_log tables existed before SQLModel was used; `init_db` creates what is missing
and adds the owner_id column to an older jobs table, so existing databases keep working.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Column, Text, UniqueConstraint, event, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: int | None = Field(default=None, primary_key=True)
    source: str = Field(index=True)            # demo | manual | greenhouse | lever
    source_id: str
    title: str
    company: str | None = None
    location: str | None = None
    description: str = Field(sa_column=Column(Text, nullable=False))
    url: str | None = None
    is_demo: bool = False
    imported_at: str = Field(default_factory=utcnow)
    extraction: str | None = Field(default=None, sa_column=Column(Text))  # JSON of the cached model output
    owner_id: int | None = Field(default=None, foreign_key="users.id", index=True)


class ImportLog(SQLModel, table=True):
    __tablename__ = "import_log"

    id: int | None = Field(default=None, primary_key=True)
    at: str = Field(default_factory=utcnow)
    source: str
    board: str | None = None
    status: str                                 # ok | error
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    message: str | None = None


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str
    password_hash: str
    created_at: str = Field(default_factory=utcnow)


class Profile(SQLModel, table=True):
    __tablename__ = "profiles"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    cv_skills: str = "[]"                       # JSON list of canonical skill names
    updated_at: str = Field(default_factory=utcnow)


class QuizResult(SQLModel, table=True):
    __tablename__ = "quiz_results"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    taken_at: str = Field(default_factory=utcnow)
    level: str = "mid"
    correct: int
    total: int
    scores: str = "{}"                          # JSON {topic: {"correct", "total", "ratio"}}


class RoadmapProgress(SQLModel, table=True):
    __tablename__ = "roadmap_progress"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    job_id: int
    done: str = "[]"                            # JSON list of step ids
    updated_at: str = Field(default_factory=utcnow)


class SavedJob(SQLModel, table=True):
    __tablename__ = "saved_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    job_id: int = Field(foreign_key="jobs.id")
    note: str | None = None
    saved_at: str = Field(default_factory=utcnow)


def make_engine(path: str | Path):
    """SQLite engine; ':memory:' gives one shared in-memory database (tests)."""
    path = str(path)
    if path == ":memory:":
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):  # SQLite enforces foreign keys only when asked
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def init_db(engine) -> None:
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:  # older databases: jobs table without owner_id
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
        if "owner_id" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN owner_id INTEGER REFERENCES users(id)"))


__all__ = ["Job", "ImportLog", "User", "Profile", "QuizResult", "RoadmapProgress", "SavedJob", "Session",
           "make_engine", "init_db", "utcnow"]

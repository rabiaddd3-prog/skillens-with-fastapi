"""Request and response models (Pydantic). They define validation and the schemas shown in /docs."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ------------------------------------------------------------------ shared inputs

class TextIn(BaseModel):
    text: str = Field(..., min_length=1, examples=["Strong Python and SQL. Git is a plus."])


class JobIn(BaseModel):
    """Import request: a pasted ad (source=manual) or a public board (greenhouse / lever)."""
    source: str = Field("manual", pattern="^(manual|greenhouse|lever)$")
    title: str | None = None
    company: str | None = None
    description: str | None = None
    board: str | None = Field(None, description="Greenhouse board token or Lever company name")
    limit: int = Field(20, ge=1, le=100)


class QuizStartIn(BaseModel):
    topics: list[str] = []
    job_id: int | None = None
    total: int = Field(25, ge=1, le=80)
    level: str = Field("mid", pattern="^(junior|mid|senior)$")


class QuizSubmitIn(BaseModel):
    session_id: str
    answers: dict[str, int]


class Evidence(BaseModel):
    cv_skills: list[str] = []
    quiz_scores: dict[str, dict] = {}


class MatchIn(Evidence):
    job_ids: list[int] | None = None


class RoadmapIn(Evidence):
    job_id: int


# ------------------------------------------------------------------ jobs CRUD

class JobCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    company: str | None = Field(None, max_length=200)
    location: str | None = Field(None, max_length=200)
    description: str = Field(..., min_length=20, description="English job text; read by the model")
    url: str | None = None


class JobUpdate(BaseModel):
    """Full replacement (PUT): every field is sent."""
    title: str = Field(..., min_length=2, max_length=200)
    company: str | None = Field(None, max_length=200)
    location: str | None = Field(None, max_length=200)
    description: str = Field(..., min_length=20)
    url: str | None = None


class JobPatch(BaseModel):
    """Partial update (PATCH): only the fields that are sent change."""
    title: str | None = Field(None, min_length=2, max_length=200)
    company: str | None = Field(None, max_length=200)
    location: str | None = Field(None, max_length=200)
    description: str | None = Field(None, min_length=20)
    url: str | None = None


class JobSummary(BaseModel):
    id: int
    source: str
    source_id: str
    title: str
    company: str | None
    location: str | None
    description: str
    url: str | None
    is_demo: bool
    imported_at: str
    owner_id: int | None = None
    extracted: bool
    image: dict | None = None
    skills: list[str] = []


class JobPage(BaseModel):
    total: int
    skip: int
    limit: int
    items: list[JobSummary]


# ------------------------------------------------------------------ users

class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=8, max_length=128)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    name: str
    created_at: str


class UserPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    password: str | None = Field(None, min_length=8, max_length=128)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class ProfileIn(BaseModel):
    cv_skills: list[str] = Field(default_factory=list, max_length=200)


class ProfileRead(BaseModel):
    cv_skills: list[str]
    updated_at: str | None


class QuizResultIn(BaseModel):
    level: str = Field("mid", pattern="^(junior|mid|senior)$")
    correct: int = Field(..., ge=0)
    total: int = Field(..., ge=1)
    scores: dict[str, dict] = Field(default_factory=dict, description="{topic: {correct, total, ratio}}")


class QuizResultRead(QuizResultIn):
    id: int
    taken_at: str


class ProgressIn(BaseModel):
    done: list[str] = Field(default_factory=list, max_length=200, description="ticked roadmap step ids")


class ProgressRead(ProgressIn):
    job_id: int
    updated_at: str | None


class SavedJobIn(BaseModel):
    job_id: int
    note: str | None = Field(None, max_length=500)


class SavedJobRead(BaseModel):
    id: int
    job_id: int
    title: str
    company: str | None
    note: str | None
    saved_at: str

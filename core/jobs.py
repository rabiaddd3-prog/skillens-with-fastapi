"""Job catalog in SQLite plus importers.

Sources:
  demo       - data/jobs_demo.json, synthetic listings written for this project (always flagged is_demo)
  manual     - English job text pasted by the user
  greenhouse - public Greenhouse Job Board API  (boards-api.greenhouse.io/v1/boards/<board>/jobs)
  lever      - public Lever Postings API        (api.lever.co/v0/postings/<company>)
The same (source, source_id) updates the existing row instead of adding a duplicate.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .i18n import LocalizedError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "jobs.db"
DEMO_FILE = ROOT / "data" / "jobs_demo.json"

class JobImportError(LocalizedError):
    """User-facing import problem (network failure, unknown board, empty result)."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def html_to_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"(?i)<\s*(br|/p|/li|/h\d|/div)\s*/?>", "\n", text)
    text = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


class JobStore:
    """Job catalog and import log on SQLModel. Methods return plain dicts so callers stay simple."""

    def __init__(self, path: str | Path = DEFAULT_DB):
        from .db import init_db, make_engine

        self.path = str(path)
        self.engine = make_engine(self.path)
        init_db(self.engine)

    def session(self):
        from sqlmodel import Session

        return Session(self.engine)

    def upsert(self, job: dict) -> tuple[int, str]:
        """Insert or update by (source, source_id). Returns (id, 'created' | 'updated' | 'unchanged')."""
        from sqlmodel import select

        from .db import Job

        for key in ("source", "source_id", "title", "description"):
            if not str(job.get(key) or "").strip():
                raise LocalizedError("job.field_required", field=key)
        fields = {"title": job["title"].strip(), "company": job.get("company"), "location": job.get("location"),
                  "description": job["description"].strip(), "url": job.get("url")}
        with self.session() as s:
            row = s.exec(select(Job).where(Job.source == job["source"],
                                           Job.source_id == str(job["source_id"]))).first()
            if row is None:
                row = Job(source=job["source"], source_id=str(job["source_id"]), is_demo=bool(job.get("is_demo", 0)),
                          owner_id=job.get("owner_id"), imported_at=now(), **fields)
                s.add(row)
                s.commit()
                return row.id, "created"
            if all(getattr(row, k) == v for k, v in fields.items()):
                return row.id, "unchanged"
            for k, v in fields.items():  # content changed: clear the cached extraction so it is recomputed
                setattr(row, k, v)
            row.imported_at, row.extraction = now(), None
            s.add(row)
            s.commit()
            return row.id, "updated"

    def update(self, job_id: int, changes: dict) -> dict | None:
        """Change title/company/location/description/url of one job; a new text clears the cached extraction."""
        from .db import Job

        with self.session() as s:
            row = s.get(Job, job_id)
            if row is None:
                return None
            for k, v in changes.items():
                if k in ("title", "company", "location", "description", "url"):
                    setattr(row, k, v.strip() if isinstance(v, str) and k in ("title", "description") else v)
            if "description" in changes or "title" in changes:
                row.extraction = None
            row.imported_at = now()
            s.add(row)
            s.commit()
            s.refresh(row)
            return self._row(row)

    def get(self, job_id: int) -> dict | None:
        from .db import Job

        with self.session() as s:
            row = s.get(Job, job_id)
            return self._row(row) if row else None

    def list(self, source: str | None = None) -> list[dict]:
        from sqlmodel import select

        from .db import Job

        q = select(Job)
        if source:
            q = q.where(Job.source == source)
        with self.session() as s:
            return [self._row(r) for r in s.exec(q.order_by(Job.id))]

    def set_extraction(self, job_id: int, extraction: dict | None) -> None:
        from .db import Job

        with self.session() as s:
            row = s.get(Job, job_id)
            if row is not None:
                row.extraction = json.dumps(extraction) if extraction is not None else None
                s.add(row)
                s.commit()

    def delete(self, job_id: int) -> bool:
        from sqlmodel import delete

        from .db import Job, SavedJob

        with self.session() as s:
            row = s.get(Job, job_id)
            if row is None:
                return False
            s.exec(delete(SavedJob).where(SavedJob.job_id == job_id))  # bookmarks of a deleted job go too
            s.delete(row)
            s.commit()
            return True

    def clear_extraction(self, job_id: int) -> None:
        self.set_extraction(job_id, None)

    def log_import(self, source: str, board: str | None, status: str, counts: dict | None = None,
                   message: str | None = None) -> None:
        from .db import ImportLog

        c = counts or {}
        with self.session() as s:
            s.add(ImportLog(at=now(), source=source, board=board, status=status, created=c.get("created", 0),
                            updated=c.get("updated", 0), unchanged=c.get("unchanged", 0), message=message))
            s.commit()

    def imports(self, limit: int = 100) -> list[dict]:
        from sqlmodel import select

        from .db import ImportLog

        with self.session() as s:
            return [r.model_dump() for r in s.exec(select(ImportLog).order_by(ImportLog.id.desc()).limit(limit))]

    @staticmethod
    def _row(row) -> dict:
        d = row.model_dump()
        d["is_demo"] = bool(d["is_demo"])
        d["extraction"] = json.loads(d["extraction"]) if d["extraction"] else None
        return d


# ------------------------------------------------------------------ importers

def manual_job(title: str, description: str, company: str | None = None) -> dict:
    if not description or len(description.strip()) < 20:
        raise LocalizedError("job.too_short")
    digest = hashlib.sha1(description.strip().encode("utf-8")).hexdigest()[:16]
    return {"source": "manual", "source_id": digest, "title": title or "Untitled job", "company": company,
            "description": description}


def demo_jobs(path: str | Path = DEMO_FILE) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [{**j, "source": "demo", "is_demo": True} for j in data["jobs"]]


def _get_json(url: str, timeout: float):
    import httpx

    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True, headers={"User-Agent": "SkillLens-student-project"})
    except httpx.HTTPError as exc:
        raise JobImportError("job.network", error=exc.__class__.__name__) from exc
    if r.status_code == 404:
        raise JobImportError("job.board_not_found")
    if r.status_code != 200:
        raise JobImportError("job.http_status", status=r.status_code)
    return r.json()


def fetch_greenhouse(board: str, limit: int = 30, timeout: float = 15.0) -> list[dict]:
    board = board.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]+", board):
        raise JobImportError("job.bad_board")
    data = _get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true", timeout)
    jobs = []
    for j in data.get("jobs", [])[:limit]:
        jobs.append({"source": "greenhouse", "source_id": f"{board}:{j['id']}", "title": j.get("title", ""),
                     "company": board, "location": (j.get("location") or {}).get("name"),
                     "description": html_to_text(j.get("content", "")), "url": j.get("absolute_url")})
    if not jobs:
        raise JobImportError("job.board_empty")
    return jobs


def fetch_lever(company: str, limit: int = 30, timeout: float = 15.0) -> list[dict]:
    company = company.strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]+", company):
        raise JobImportError("job.bad_company")
    data = _get_json(f"https://api.lever.co/v0/postings/{company}?mode=json", timeout)
    jobs = []
    for j in (data if isinstance(data, list) else [])[:limit]:
        parts = [j.get("descriptionPlain") or html_to_text(j.get("description", ""))]
        for block in j.get("lists", []):
            parts.append(block.get("text", ""))
            parts.append(html_to_text(block.get("content", "")))
        jobs.append({"source": "lever", "source_id": f"{company}:{j['id']}", "title": j.get("text", ""),
                     "company": company, "location": (j.get("categories") or {}).get("location"),
                     "description": "\n".join(p for p in parts if p), "url": j.get("hostedUrl")})
    if not jobs:
        raise JobImportError("job.company_empty")
    return jobs

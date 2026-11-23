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
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .i18n import LocalizedError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "jobs.db"
DEMO_FILE = ROOT / "data" / "jobs_demo.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    title        TEXT NOT NULL,
    company      TEXT,
    location     TEXT,
    description  TEXT NOT NULL,
    url          TEXT,
    is_demo      INTEGER NOT NULL DEFAULT 0,
    imported_at  TEXT NOT NULL,
    extraction   TEXT,
    UNIQUE (source, source_id)
);
CREATE TABLE IF NOT EXISTS import_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        TEXT NOT NULL,
    source    TEXT NOT NULL,
    board     TEXT,
    status    TEXT NOT NULL,      -- ok | error
    created   INTEGER NOT NULL DEFAULT 0,
    updated   INTEGER NOT NULL DEFAULT 0,
    unchanged INTEGER NOT NULL DEFAULT 0,
    message   TEXT
)
"""


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
    def __init__(self, path: str | Path = DEFAULT_DB):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert(self, job: dict) -> tuple[int, str]:
        """Insert or update by (source, source_id). Returns (id, 'created' | 'updated' | 'unchanged')."""
        for key in ("source", "source_id", "title", "description"):
            if not str(job.get(key) or "").strip():
                raise LocalizedError("job.field_required", field=key)
        row = self.conn.execute("SELECT id, title, description, company, location, url FROM jobs "
                                "WHERE source=? AND source_id=?", (job["source"], str(job["source_id"]))).fetchone()
        fields = (job["title"].strip(), job.get("company"), job.get("location"), job["description"].strip(),
                  job.get("url"))
        if row is None:
            cur = self.conn.execute(
                "INSERT INTO jobs (source, source_id, title, company, location, description, url, is_demo, imported_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (job["source"], str(job["source_id"]), *fields[:4], fields[4], int(job.get("is_demo", 0)), now()))
            self.conn.commit()
            return cur.lastrowid, "created"
        if (row["title"], row["company"], row["location"], row["description"], row["url"]) == fields:
            return row["id"], "unchanged"
        # Content changed: clear the cached extraction so it is recomputed.
        self.conn.execute("UPDATE jobs SET title=?, company=?, location=?, description=?, url=?, imported_at=?, "
                          "extraction=NULL WHERE id=?", (*fields, now(), row["id"]))
        self.conn.commit()
        return row["id"], "updated"

    def get(self, job_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, source: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM jobs", ()
        if source:
            q, args = q + " WHERE source=?", (source,)
        return [self._row(r) for r in self.conn.execute(q + " ORDER BY id", args)]

    def set_extraction(self, job_id: int, extraction: dict) -> None:
        self.conn.execute("UPDATE jobs SET extraction=? WHERE id=?", (json.dumps(extraction), job_id))
        self.conn.commit()

    def delete(self, job_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def clear_extraction(self, job_id: int) -> None:
        self.conn.execute("UPDATE jobs SET extraction=NULL WHERE id=?", (job_id,))
        self.conn.commit()

    def log_import(self, source: str, board: str | None, status: str, counts: dict | None = None,
                   message: str | None = None) -> None:
        c = counts or {}
        self.conn.execute("INSERT INTO import_log (at, source, board, status, created, updated, unchanged, message)"
                          " VALUES (?,?,?,?,?,?,?,?)", (now(), source, board, status, c.get("created", 0),
                                                        c.get("updated", 0), c.get("unchanged", 0), message))
        self.conn.commit()

    def imports(self, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM import_log ORDER BY id DESC LIMIT ?", (limit,))]

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
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

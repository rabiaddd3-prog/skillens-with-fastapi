"""Check that every course URL in data/courses.json still answers. Re-run before the demo.

Usage: python scripts/check_course_links.py
"""
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / "data" / "courses.json").read_text(encoding="utf-8"))["courses"]
topics = json.loads((ROOT / "data" / "roadmap.json").read_text(encoding="utf-8"))["topics"]
unknown = set(data) - {t["id"] for t in topics}
if unknown:
    sys.exit(f"courses.json has topics missing from roadmap.json: {sorted(unknown)}")

bad = 0
with httpx.Client(follow_redirects=True, timeout=20, headers={"User-Agent": "Mozilla/5.0 (SkillLens link check)"}) as client:
    for topic, courses in data.items():
        for c in courses:
            try:
                status = client.get(c["url"]).status_code
            except httpx.HTTPError as exc:
                status = type(exc).__name__
            # Udemy answers bots with 403 even for valid pages; report it but do not count it as broken.
            ok = status == 200 or (status == 403 and "udemy.com" in c["url"])
            bad += not ok
            print(f"{'ok ' if ok else 'BAD'} {status!s:>5}  {topic:18s} {c['provider']:18s} {c['url']}")
print(f"\n{bad} broken link(s)")
sys.exit(1 if bad else 0)

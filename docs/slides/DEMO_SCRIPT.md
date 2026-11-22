# Demo checklist

Before the presentation:

1. `python scripts/check_course_links.py`: all Patika/BTK links should be `ok 200`.
2. Start the app: `python -m uvicorn api.main:app --port 8000`, open http://127.0.0.1:8000.
3. `/health` badge in the header must say the model is loaded. If not, the `checkpoints/distilbert`
   folder is missing.
4. Hard-refresh the browser (Ctrl+F5) once.

Demo flow (brief scenario, about 3 minutes):

| Step | Do | Expected |
|---|---|---|
| CV | paste `Python developer who uses Git daily.` → Analyse → Confirm | Python, Git |
| Jobs | open *Junior Backend Developer (Python)* | Python, SQL, Git highlighted in the ad |
| Quiz | topics Python + SQL, 10 questions | per-topic scores, answers revealed after submit |
| Matches | look at the first job | Git = CV only, SQL weak if you scored < 60% |
| Roadmap | open the roadmap for that job | SQL fundamentals with course links |
| Model lab | press *Extract spans* | comparison tables + highlighted text |

Optional (needs internet): Jobs → Import live listings → Greenhouse → `gitlab`.

If something fails: the demo jobs work offline; the quiz and matching do not need the network.

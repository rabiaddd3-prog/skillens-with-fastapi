# SkillLens

Deep learning-based developer skill assessment and job matching.

SkillLens reads English job ads, extracts **Skill** and **Knowledge** requirements with a token
classifier, compares them with the skills claimed in a CV and with per-topic quiz results, ranks
jobs with an explainable score, and builds a learning roadmap with course links.

Research question: *how accurately and how fast do a BiLSTM and a fine-tuned DistilBERT extract
skill and knowledge spans from the same job-ad data (SkillSpan)?*

## Results (SkillSpan test split, 3,569 sentences)

Entity-level scores: a predicted span counts only if its sentence, start, end and type all match.
Latency: per sentence, batch size 1, 500 test sentences after 20 warm-up runs, including
tokenisation and decoding, on an RTX 3050 Ti Laptop GPU. Main run: seed 42.

| Model | F1 overall | F1 skill | F1 knowledge | Precision | Recall | Median latency |
|---|---|---|---|---|---|---|
| BiLSTM | 0.400 | 0.275 | 0.508 | 0.407 | 0.394 | 2.2 ms |
| DistilBERT | 0.530 | 0.429 | 0.621 | 0.512 | 0.548 | 6.2 ms |

Source: `results/test_metrics.json` and `results/comparison.csv`, produced by `scripts/evaluate.py`.

Over three training seeds (42, 13, 7; mean ± standard deviation, `results/seed_summary.json`):

| Model | F1 overall | F1 skill | F1 knowledge | Median latency |
|---|---|---|---|---|
| BiLSTM | 0.395 ± 0.006 | 0.275 ± 0.010 | 0.499 ± 0.008 | 1.75 ± 0.40 ms |
| DistilBERT | 0.538 ± 0.008 | 0.438 ± 0.008 | 0.627 ± 0.007 | 6.25 ± 0.13 ms |

Reproduce with `python scripts/run_seeds.py --seeds 13 7` and `python scripts/aggregate_seeds.py`.
The app uses the seed-42 checkpoints.
Error examples (false positive, false negative, boundary) are in `results/errors_*.jsonl`.

### Extra analyses

`python scripts/analyze_by_source.py` (from the saved predictions, no retraining): F1 separately
for the TECH and HOUSE job ads of the test split, mean ± std over the three seeds, and a
dictionary-only baseline (every `data/skills.json` match tagged as Knowledge). Output:
`results/by_source.csv`, `results/dictionary_baseline.json`.

| | F1 overall TECH | F1 overall HOUSE | F1 knowledge (all) |
|---|---|---|---|
| Dictionary only | 0.264 | 0.065 | 0.312 (P 0.653, R 0.205) |
| BiLSTM | 0.466 ± 0.003 | 0.306 ± 0.016 | 0.499 ± 0.008 |
| DistilBERT | 0.591 ± 0.005 | 0.475 ± 0.011 | 0.627 ± 0.007 |

`python scripts/ablation_jobs.py [--embed]`: on the 25 catalog jobs, the canonical skills from the
dictionary alone, from the model alone and from the app (model + dictionary). Output:
`results/ablation_jobs.json`, `results/ablation_jobs_embed.json`. Without the Sentence-BERT
fallback the app's skill set equals the dictionary's on every job, and 90% of the model's
requirements (44 of 49 per job on average) have no canonical skill. With the fallback at
similarity 0.75, 3 of 25 jobs gain a skill. `results/embed_candidates.csv` lists every
unmatched phrase with its nearest skill name and similarity, with an empty `correct` column for
a manual check of the threshold.

`python scripts/sensitivity.py`: rankings of the catalog jobs for 500 random synthetic profiles
(not real users) with other CV/quiz weights, compared with the default 0.5/0.5 (Kendall's tau,
same top job, top-3 overlap); and how many skill statuses change with another weak-quiz threshold.
Output: `results/sensitivity.json`.

`scripts/gold_match.py` with `docs/gold_match/`: a human-labelled check of the ranking. The
labelling sheet is made without the system's scores; the labels must be filled in by a person.

## Setup

Python 3.11 (tested; the course lab uses 3.12, which the code does not exclude but was not tested). From the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\activate                     # macOS/Linux: source .venv/bin/activate
# PyTorch: pick the build for your machine
pip install torch --index-url https://download.pytorch.org/whl/cu118   # NVIDIA GPU (CUDA 11.8)
# pip install torch                                                    # CPU or Apple Silicon (MPS)
pip install -r requirements.txt
```

The device is chosen automatically: CUDA, then Apple MPS, then CPU.

## Train and evaluate

```powershell
python scripts/inspect_skillspan.py                 # dataset splits, schema, label counts
python scripts/check_bert_alignment.py              # subword/label alignment round trip
python scripts/train_bilstm.py --out checkpoints/bilstm
python scripts/train_distilbert.py --out checkpoints/distilbert
python scripts/evaluate.py --bilstm checkpoints/bilstm --distilbert checkpoints/distilbert --out results
```

Smoke tests (check that the code runs; not results):

```powershell
python scripts/train_bilstm.py --limit-train 200 --limit-val 100 --epochs 2 --out runs/smoke_bilstm
python scripts/train_distilbert.py --limit-train 200 --limit-val 100 --epochs 1 --out runs/smoke_distilbert
```

Each run writes `run_info.json` (settings, versions, device), `history.json` (loss and validation
F1 per epoch) and `best_val_scores.json`. The checkpoint with the best validation F1 is kept; the
test split is only used by `evaluate.py`. Checkpoints are not in the repository (DistilBERT is
about 260 MB): either train them with the commands above, or unzip `skilllens_checkpoints.zip`
(both trained models, 234 MB, SHA-256 `36B677563E9016D02E5CE36B1D8333D344AC1B9B593119807CD75DC0CE00FDEB`)
into the project folder so that `checkpoints/bilstm` and `checkpoints/distilbert` exist.

Report figures and LaTeX tables are generated from the measured files:

```powershell
python scripts/make_figures.py      # -> docs/report/figures/, docs/report/tables/
```

## Run the app

```powershell
fastapi dev main.py                              # development: auto-reload on save
python -m uvicorn api.main:app --port 8000       # or plain uvicorn
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000   # reachable from other devices on the same network
```

Open http://127.0.0.1:8000. The FastAPI backend serves both the API (docs at `/docs`) and the
web frontend. Configuration through environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `SKILLLENS_MODEL` | `distilbert` | `distilbert` or `bilstm` |
| `SKILLLENS_CHECKPOINT` | `checkpoints/<model>` | checkpoint folder |
| `SKILLLENS_DB` | `data/jobs.db` | SQLite job catalog |
| `SKILLLENS_DEVICE` | `auto` | `auto`, `cpu`, `cuda`, `mps` |
| `SKILLLENS_ADMIN_TOKEN` | random | token for the admin page |
| `SKILLLENS_EMBED` | `1` | `0` turns off the Sentence-BERT fallback for model phrases the dictionary cannot name |
| `SKILLLENS_EMBED_THRESHOLD` | `0.75` | cosine similarity the fallback needs |
| `SKILLLENS_AUTO_IMPORT` | none | boards imported on a schedule, e.g. `greenhouse:gitlab,lever:acme` |
| `SKILLLENS_IMPORT_HOURS` | `24` | hours between scheduled imports (the first round runs at start) |

If the checkpoint is missing, `/health` reports why and extraction endpoints answer 503 with a
clear message.

The interface is available in English and Turkish (button in the header). The page sends the
choice as an `X-Lang: en|tr` header; the API then returns errors, matching notes, roadmap texts,
quiz questions (`data/quiz_bank_tr.json`) and the PDF summary in that language. Job ads and the
model's highlights stay English, because the model was trained on English postings.

Other views: the model comparison tab can run both models side by side on any text (both
checkpoints are loaded at start when `SKILLLENS_CHECKPOINT` is not set); the job view compares
each requirement with the CV line that backs it; the quiz step keeps a progress chart of finished
quizzes (stored only in the browser's localStorage); the matches step shows which skills the
listed jobs ask for most, coloured by the user's evidence.

The site opens on a home page (live numbers from the API and the measured results, a sample
sentence read by the model, featured jobs). During the assessment a profile panel beside the
steps sums up the confirmed CV, the selected job, quiz scores, the best match and roadmap
progress; roadmap steps can be ticked off (stored in the browser).

**Admin page** (`/admin`): overview (model, jobs, question bank, API calls and average time since
the server started), job catalog (re-extract, delete), import log and the question bank with
answers. Sign in with `SKILLLENS_ADMIN_TOKEN`; if it is not set, the server makes a new token at
each start, prints it and writes it to `runs/admin_token.txt`.

### API

| Endpoint | Purpose |
|---|---|
| `GET /health` | API and model status |
| `POST /cv/analyze` | text-based PDF upload → candidate skills (nothing stored) |
| `POST /cv/analyze-text` | pasted CV text → candidate skills |
| `POST /jobs/import` | add a pasted job, or import from Greenhouse / Lever |
| `GET /jobs`, `GET /jobs/{id}` | job catalog; a job's extracted requirements |
| `POST /skills/extract` | English text → Skill/Knowledge spans with character offsets |
| `POST /skills/compare` | the same text through BiLSTM and DistilBERT: spans, server time, spans only one model found |
| `GET /quiz/topics`, `POST /quiz/start`, `POST /quiz/submit` | topic quiz; answers stay on the server until submit |
| `POST /matches` | ranked jobs with CV coverage, quiz performance, quiz coverage |
| `POST /roadmap` | ordered learning steps with prerequisites and courses |
| `GET /results/comparison` | the measured model comparison |
| `GET /admin` | admin page; its API is under `/admin/api/*` and needs the `X-Admin-Token` header |

Accounts and saved data (bearer token; see the next section):

| Endpoint | Purpose |
|---|---|
| `POST /auth/register` | create an account (201; 409 if the e-mail exists) |
| `POST /auth/token` | sign in (OAuth2 password form) → JWT access token |
| `GET / PATCH / DELETE /users/me` | own account: read, change name or password, delete with all data |
| `GET / PUT /users/me/profile` | confirmed CV skills |
| `GET / POST /users/me/quiz-results`, `DELETE /users/me/quiz-results/{id}` | finished quizzes |
| `GET /users/me/roadmaps`, `GET / PUT /users/me/roadmaps/{job_id}` | ticked roadmap steps |
| `GET / POST /users/me/saved-jobs`, `DELETE /users/me/saved-jobs/{job_id}` | bookmarked jobs |
| `POST /jobs`, `PUT / PATCH / DELETE /jobs/{id}` | create a job, and change or delete jobs you created (403 for others' jobs) |
| `GET /jobs?source=&q=&skill=&skip=&limit=` | filter, search and paginate; total in the `X-Total-Count` header |

### FastAPI structure (Advanced Computer Programming)

The same application is the FastAPI project of the Advanced Computer Programming course
(the NLP course version is frozen at the git tag `nlp-final`).

* **Routers** (`api/routers/`): `auth`, `users`, `jobs`, `cv`, `skills`, `quiz`, `matching`, `admin`,
  `system`; each has its own tag and description in `/docs` and `/redoc`.
* **Database**: SQLite through **SQLModel** (`core/db.py`): `jobs`, `import_log`, `users`,
  `profiles`, `quiz_results`, `roadmap_progress`, `saved_jobs`. `data/jobs.db` can be opened with
  the VS Code SQLite Viewer. An older database is upgraded at start (missing tables and the
  `jobs.owner_id` column are added).
* **Security** (`api/security.py`): passwords are stored as Argon2 hashes (pwdlib); sign-in returns
  a JWT (HS256, one day) that is sent as `Authorization: Bearer …`. The **Authorize** button in
  `/docs` uses the same `/auth/token` endpoint. Users only see and change their own rows; jobs created
  with `POST /jobs` can only be changed by their creator. The admin API uses a separate token header.
* **Dependencies**: `Depends` for the database session, the signed-in user, the admin check and the
  message language (`X-Lang`). **Validation** with Pydantic models (`api/schemas.py`), including
  e-mail format and minimum password length. **Status codes**: 201 create, 204 delete, 401 / 403 /
  404 / 409 / 422 errors with messages in English or Turkish.
* **Also used**: lifespan start-up (database, model, secrets), HTTP middleware (per-route call
  count and time on the admin page), background task (scheduled job import), file upload (CV PDF),
  file download (PDF summary), static files (the web frontend), optional CORS (`SKILLLENS_CORS`).
* **Frontend**: a *Sign in* button in the header; when signed in, CV skills, quiz results, roadmap
  ticks and saved jobs (star on the job view) are stored on the server and come back on any device.
  Without an account everything still works and stays in the browser.

| Variable | Default | Meaning |
|---|---|---|
| `SKILLLENS_JWT_SECRET` | random, kept in `runs/jwt_secret.txt` | secret for sign-in tokens |
| `SKILLLENS_CORS` | none | comma-separated origins allowed to call the API from a browser |

### Scoring

* CV coverage = job skills found in the confirmed CV / all job skills
* Quiz performance = mean quiz ratio over the job's quiz topics that were measured
* Quiz coverage = measured job quiz topics / all job quiz topics
* Combined = 0.5 × CV coverage + 0.5 × quiz performance; if no job topic was measured, combined = CV coverage
* A job with no recognised skills is reported as "could not be calculated"
* A quiz topic below 60% counts as weak evidence
* Job skills: model spans named by the dictionary; dictionary hits the model missed are added and
  flagged; model spans the dictionary cannot name are mapped with Sentence-BERT
  (`sentence-transformers/all-MiniLM-L6-v2`, downloaded once, about 90 MB) to the most similar
  skill name if the cosine similarity is at least 0.75, and shown as such in the job view

## Tests

```powershell
python -m pytest -q tests
```

Covers BIO/span conversion, metric agreement with `seqeval`, DistilBERT label alignment, both models
(padding, overfitting a tiny set, checkpoint round trip), CV errors (empty, not a PDF, too large,
damaged, scanned), job upsert, quiz (hidden answers, shuffled options), matching, roadmap ordering,
the API, and the demo scenario (CV: Python, Git; job: Python, SQL, Git; quiz: Python strong, SQL weak).

## Project layout

```
core/        model, data and application logic (no web code)
  data.py, labels.py, metrics.py, errors.py   dataset encoding, BIO spans, entity metrics, error types
  bilstm.py, distilbert.py                    the two taggers (shared encoder + Skill/Knowledge heads)
  extractor.py                                raw text → spans with offsets → canonical skills
  skills.py, cv.py, jobs.py, quiz.py          dictionary, CV parsing, job catalog/importers, quiz
  matching.py, roadmap.py                     scores and learning path
main.py      entry point for `fastapi dev` / `fastapi run`
api/         FastAPI app: main.py (app, lifespan, middleware), state.py (shared dependencies),
             security.py (hashing, JWT), schemas.py (request/response models), routers/
core/db.py   SQLModel tables
web/         frontend (HTML/CSS/JS, no external assets)
scripts/     training, evaluation, data checks, link check
data/        skill dictionary, quiz bank, roadmap topics, course links, demo jobs
results/     measured test-set results
tests/       pytest suite
docs/        brief, data notes, report skeleton, slides skeleton
```

## Data and sources

* **SkillSpan** (Zhang et al., NAACL 2022), loaded from Hugging Face `jjzha/skillspan`; official
  train/validation/test splits. See `docs/data_notes.md` for counts and checks. Licence: the
  Hugging Face card lists CC BY 4.0; the paper states that the TECH source postings (Stack Overflow
  Jobs) are CC BY-SA. The data is downloaded at training time and not redistributed in this repository.
* **DistilBERT** `distilbert-base-cased` from Hugging Face.
* `data/jobs_demo.json`: synthetic job ads written for this prototype; companies are fictional and
  every demo job is labelled *demo* in the app.
* `web/img/jobs/`: representative stock photos for the demo jobs from Pexels (Pexels License); the
  photographer and source page of each are in `data/job_images.json` and shown under the photo.
* `web/fonts/`: Source Serif 4 (SIL Open Font License), served locally so the app works offline.
* `data/courses.json`: course pages on Patika (Skillcamp), BTK Akademi and Udemy, checked on
  2026-11-22. Re-check with `python scripts/check_course_links.py` (Udemy answers automated requests
  with 403, which the script reports but does not count as broken).
* Live job import uses the public Greenhouse Job Board API and Lever Postings API. Checked on
  2026-11-22: importing 15 jobs from the Greenhouse board `gitlab` created 15 records, a second
  import left all 15 unchanged, the model extracted requirements from a real posting, and an unknown
  board returned a clear error. Lever (`spotify`, `palantir`) also returned postings.

## Report and presentation

* `docs/report/`: Springer LNCS skeleton (`main.tex`), bibliography, TikZ architecture diagram,
  pseudocode, generated figures and tables. Compile on Overleaf with the LNCS template.
* `docs/slides/`: Beamer skeleton and `DEMO_SCRIPT.md` (pre-demo checklist and click path).

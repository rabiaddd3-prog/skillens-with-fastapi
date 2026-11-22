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

## Setup

Python 3.11. From the project folder:

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
python -m uvicorn api.main:app --port 8000
```

Open http://127.0.0.1:8000. The FastAPI backend serves both the API (docs at `/docs`) and the
web frontend. Configuration through environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `SKILLLENS_MODEL` | `distilbert` | `distilbert` or `bilstm` |
| `SKILLLENS_CHECKPOINT` | `checkpoints/<model>` | checkpoint folder |
| `SKILLLENS_DB` | `data/jobs.db` | SQLite job catalog |
| `SKILLLENS_DEVICE` | `auto` | `auto`, `cpu`, `cuda`, `mps` |

If the checkpoint is missing, `/health` reports why and extraction endpoints answer 503 with a
clear message.

### API

| Endpoint | Purpose |
|---|---|
| `GET /health` | API and model status |
| `POST /cv/analyze` | text-based PDF upload → candidate skills (nothing stored) |
| `POST /cv/analyze-text` | pasted CV text → candidate skills |
| `POST /jobs/import` | add a pasted job, or import from Greenhouse / Lever |
| `GET /jobs`, `GET /jobs/{id}` | job catalog; a job's extracted requirements |
| `POST /skills/extract` | English text → Skill/Knowledge spans with character offsets |
| `GET /quiz/topics`, `POST /quiz/start`, `POST /quiz/submit` | topic quiz; answers stay on the server until submit |
| `POST /matches` | ranked jobs with CV coverage, quiz performance, quiz coverage |
| `POST /roadmap` | ordered learning steps with prerequisites and courses |
| `GET /results/comparison` | the measured model comparison |

### Scoring

* CV coverage = job skills found in the confirmed CV / all job skills
* Quiz performance = mean quiz ratio over the job's quiz topics that were measured
* Quiz coverage = measured job quiz topics / all job quiz topics
* Combined = 0.5 × CV coverage + 0.5 × quiz performance; if no job topic was measured, combined = CV coverage
* A job with no recognised skills is reported as "could not be calculated"
* A quiz topic below 60% counts as weak evidence

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
api/main.py  FastAPI app (also serves web/)
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

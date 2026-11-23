# Gold set for the job ranking

The ranking has no human-checked reference yet. This folder holds one.

1. Edit `profiles.json`: replace the example with 3–5 real profiles (your own CV, classmates'
   with their permission, or public example CVs). `cv_skills` uses the canonical names from
   `data/skills.json`; `quiz` holds the ratios a person really got in the app.
2. `python scripts/gold_match.py template` writes `labels.csv` in random order, without the
   system's scores. Read each job ad and fill `relevance`: 0 = does not fit, 1 = partly, 2 = fits well.
   Label before looking at the app's ranking for that profile.
3. `python scripts/gold_match.py score` writes `results/gold_match.json` (NDCG@5, precision@3,
   Spearman) for CV-only, combined and random ranking.

The labels must come from a person. Do not fill them from the app's own scores.

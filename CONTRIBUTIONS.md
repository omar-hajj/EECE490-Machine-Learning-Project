# Contribution log

Required in the final submission (roadmap: "Record who did what in a shared
contribution log from day 1"). Add a row whenever you push work. Use your
name, not only your GitHub handle, before submitting.

Team: Omar El Hajj, Houssein Karnib, Sami Marouni.

## Roles

| Stream | Owner | Scope |
| --- | --- | --- |
| A: Data | _name_ | Cleaning, weather data, features, data provenance, Responsible ML write-up |
| B: Models | _name_ | Baselines, ML models, evaluation, error analysis, constraint test |
| C: Product | _name_ | Repository structure, generator logic, API, Docker, interface, README |

## Log

| Date | Who | Stream | Work | Where |
| --- | --- | --- | --- | --- |
| 2026-11-04 | Jana | All | Wrote the 3-week roadmap | `EECE490_3-Week_Roadmap.docx` |
| 2026-11-08 | Omar | C | Created the GitHub repository | initial commit |
| 2026-11-09 | hmk0619 | A, B | Data audit; complete-hour hourly preparation; three baselines; Ridge and XGBoost (history/calendar and forecast weather); direct net-load P90; May–July backtests and July calibration check; village weather download; location-only trial; output verifiers; 59 tests | `src/lebanon_energy/`, `scripts/`, `*_RESULTS.md`, `DATA_AUDIT.md` |
| 2026-11-09 | hmk0619 | C | FastAPI `/forecast` demo serving Ridge demand and weekday-profile PV with explicit fallbacks | `src/lebanon_energy/api/service.py` |
| 2026-11-10 | Omar | C | Observed generator capacities and draft selection rule from the Azm status/power columns | `src/lebanon_energy/generators/capacity.py`, `config/azm_generators.json`, `GENERATORS.md` |
| 2026-11-10 | Omar | B | Use-linked metric: wrong-generator hours (undersized vs. oversized) for every validation method | `src/lebanon_energy/evaluation/generator_choice.py`, `generators/policy.py` (`choice_errors`) |
| 2026-11-10 | Omar | C | First Dockerfile, compose file and serving requirements; started this log | `Dockerfile`, `docker-compose.yml`, `requirements-serve.lock.txt` |
| 2026-11-10 | Omar | A | Week 1 data checks: Azm load jumps, Household 3 meter freeze (masked) and power balance, reproducible check script | `DATA_PROVENANCE.md`, `scripts/data_checks.py`, `config/baseline.json` |
| 2026-11-10 | Omar | A | Lebanese public holiday list with sources, calendar columns; scripted Azm weather download; hourly generator columns | `config/lebanon_public_holidays.csv`, `scripts/build_calendar.py`, `scripts/download_azm_weather.py`, `scripts/build_hourly_generators.py` |
| 2026-11-10 | Omar | A | Data provenance note: sources, every change, excluded files checked against the data, open questions for the school | `DATA_PROVENANCE.md` |
| 2026-11-10 | Omar | B | Daily peak error for Azm and Household 3 | `src/lebanon_energy/evaluation/peak_scores.py`, `MODEL_RESULTS.md` |
| 2026-11-10 | Omar | C | Split the code into data, features, models, evaluation, generators, api and app folders | `src/lebanon_energy/` |
| 2026-11-15 | Omar | B | Daily rolling-origin check of net load (baselines, Ridge, XGBoost, change-from-last-week, forecast weather, four upper estimates); model choice; comparison with what the operator ran; run log | `src/lebanon_energy/models/walk_forward.py`, `config/walk_forward.json`, `WEEK2_RESULTS.md`, `results/run_log.csv` |
| 2026-11-15 | Omar | A | Holiday-aware features; feature table and leakage check; missing-input test sets and evaluation | `src/lebanon_energy/features/holidays.py`, `evaluation/leakage.py`, `evaluation/missing_inputs.py` |
| 2026-11-15 | Omar | B | Error analysis by hour, day type, temperature and holiday; 3 worst days; Household 3 transfer check; guarded one-shot September test script, rehearsed on August | `src/lebanon_energy/evaluation/error_analysis.py`, `evaluation/final_test.py`, `WEEK3_ANALYSIS.md` |
| 2026-11-15 | Omar | A | Exact explanations of the Ridge forecast; Responsible ML write-up (explainability, distribution shift, human oversight) and limitations | `src/lebanon_energy/models/explain.py`, `WEEK3_ANALYSIS.md` |
| 2026-11-15 | Omar | C | Why panel, Backtest page and Failure gallery; backtest table; peak drivers in the API | `src/lebanon_energy/app/main.py`, `evaluation/backtest_table.py`, `api/service.py` |
| 2026-11-15 | Omar | B | September final test, run once; results table, first-week analysis, worst days and final recommendation | `results/final_test_azm.json`, `FINAL_RESULTS.md` |
| 2026-11-15 | Omar | All | Draft poster panels, 5-minute presentation outline and prepared Q&A answers | `docs/POSTER.md`, `docs/PRESENTATION.md` |
| 2026-11-15 | Omar | C | Fresh-clone test on the same laptop (clone, install from lock files, tests, full pipeline, results compared); README table mapping each results table to its command | `README.md` |
| 2026-11-15 | Omar | C | Served model bundle; API returns upper estimate, generator recommendation, fallbacks and input status; minimum-run rule; Streamlit Tomorrow view and Trust banner; second Dockerfile and two-service compose file; README quick start | `src/lebanon_energy/models/serving.py`, `api/service.py`, `app/main.py`, `generators/policy.py`, `Dockerfile.app`, `docker-compose.yml` |

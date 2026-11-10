# Contribution log

Required in the final submission (roadmap: "Record who did what in a shared
contribution log from day 1"). Add a row whenever you push work. Use your
name, not only your GitHub handle, before submitting.

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
| 2026-11-09 | hmk0619 | C | FastAPI `/forecast` demo serving Ridge demand and weekday-profile PV with explicit fallbacks | `src/lebanon_energy/api.py` |
| 2026-11-10 | Omar | C | Observed generator capacities and draft selection rule from the Azm status/power columns | `src/lebanon_energy/generator_capacity.py`, `config/azm_generators.json`, `GENERATORS.md` |
| 2026-11-10 | Omar | B | Use-linked metric: wrong-generator hours (undersized vs. oversized) for every validation method | `src/lebanon_energy/generator_choice.py`, `generators.choice_errors` |
| 2026-11-10 | Omar | C | First Dockerfile, compose file and serving requirements; started this log | `Dockerfile`, `docker-compose.yml`, `requirements-serve.lock.txt` |

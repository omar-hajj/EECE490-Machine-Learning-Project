# EECE490 Machine Learning Project

Day-ahead forecast of electricity load and solar production for Azm, used to
recommend which diesel generator to run each hour. Household 3 is the second
site for checking that the method transfers.

**Status (November 15, 2026): all three weeks built; the September final test has been run once ([FINAL_RESULTS.md](FINAL_RESULTS.md)).**

| Read this | For |
|---|---|
| [FINAL_RESULTS.md](FINAL_RESULTS.md) | **September final test**: results table, what held, what failed, final recommendation |
| [MODEL_TUNING.md](MODEL_TUNING.md) | Model scored with the course's chapter 6 metrics (MBE/MAE/RMSE, train-test gap, confusion matrix, McNemar, Z-test) and tuned on validation folds; the tuned model is not yet served; clean test of the tuning on Household 3's July |
| [WEEK2_RESULTS.md](WEEK2_RESULTS.md) | Model choice, generator advice, missing-input test, leakage check |
| [WEEK3_ANALYSIS.md](WEEK3_ANALYSIS.md) | Error analysis, 3 worst days, explainability, distribution shift, human oversight, Household 3 transfer, limitations, final-test procedure |
| [GENERATORS.md](GENERATORS.md) | Observed capacities, draft selection rule, wrong-generator metric |
| [MODEL_RESULTS.md](MODEL_RESULTS.md), [BASELINE_RESULTS.md](BASELINE_RESULTS.md) | Week 1 baselines, Ridge, XGBoost, first P90 |
| [DATA_PROVENANCE.md](DATA_PROVENANCE.md) | Sources, every change to the data, excluded files |
| [docs/POSTER.md](docs/POSTER.md), [docs/PRESENTATION.md](docs/PRESENTATION.md) | Draft poster panels; 5-minute outline and prepared Q&A answers |
| [CONTRIBUTIONS.md](CONTRIBUTIONS.md) | Who did what |
| [PROJECT_PLAN.md](PROJECT_PLAN.md), [LOCATION_ONLY_RESULTS.md](LOCATION_ONLY_RESULTS.md) | Earlier scope and the exploratory location-only trial |

In short: a holiday-aware Ridge forecast of net load, plus a margin taken
from its own recent errors, keeps about 9 hours in 10 below the upper
estimate in every month tested. XGBoost and forecast weather did not earn
their place. The operator's actual choices were larger than needed in 65% of
hours; the forecast rule would cut that to about 20% with 0.4% of hours
undersized. On the unseen test month (September) the same method was still
the best of those compared: 20.2% error against 22.4% for the baseline,
88.7% coverage, and 2.4% of hours undersized, nearly all in the first week
of term. Household 3's reserved July 2025 was then used once, to test the
tuning procedure (8% lower error than untuned); the other village sites'
July remains unscored.

## Quick start

The data ZIP is not in Git. Put `Data for EECE 490 Project.zip` in the folder
above this one (or pass its path to `--archive`). From this folder, in
PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-api.lock.txt
.\.venv\Scripts\python.exe -m pip install streamlit==1.67.0 plotly==7.1.0
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Build the hourly data and the served model, then start the API and the page:

```powershell
.\.venv\Scripts\python.exe scripts/run_baselines.py --archive '..\Data for EECE 490 Project.zip' --config config/baseline.json --sites config/sites.json --output-dir outputs/baselines_confirmed_azm
.\.venv\Scripts\python.exe scripts/build_serving_bundle.py
.\.venv\Scripts\python.exe -m uvicorn lebanon_energy.api.service:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m streamlit run src/lebanon_energy/app/main.py
```

The API is at http://localhost:8000/docs and the page at
http://localhost:8501. The Backtest page and Failure gallery also need the
logged results (about 4 minutes):

```powershell
.\.venv\Scripts\python.exe scripts/walk_forward.py
.\.venv\Scripts\python.exe scripts/build_backtest_table.py
.\.venv\Scripts\python.exe scripts/analyse_errors.py
```

With Docker, `docker compose up --build` starts both services after the
build commands above. Minimal API request:

```json
{"issue_time_local": "2026-08-10T00:00:00", "readings": []}
```

With no readings the answer uses the weekday-average fallback and says so in
`input_status`. Readings are complete hourly averages in kW:
`{"timestamp_local": "2026-08-09T23:00:00", "load_kw": 80.5, "pv_kw": 0.0}`.

## Reproduce each results table

Every command is run as `.\.venv\Scripts\python.exe scripts/<name>.py` from
this folder, after `run_baselines.py` (Quick start). Outputs go to
`outputs/`; scores are also appended to `results/run_log.csv`.

| Table | Where | Script | Needs first |
|---|---|---|---|
| Baselines on validation | BASELINE_RESULTS.md | `run_baselines.py` (arguments in Quick start) | data ZIP |
| Ridge / XGBoost per site, first P90 | MODEL_RESULTS.md | `train_ridge.py`, `train_xgboost.py`, `train_quantile.py` (arguments under "Model experiments") | baselines |
| Daily peak error | MODEL_RESULTS.md | `score_daily_peaks.py` | Ridge, XGBoost |
| Wrong-generator hours, August | GENERATORS.md | `score_generator_choice.py` | Ridge, XGBoost, P90 |
| Point forecasts and upper estimates, May–August | WEEK2_RESULTS.md | `prepare_weather_features.py` (arguments in WEEK2_RESULTS.md), then `walk_forward.py` | baselines |
| Operator practice vs. forecast rule | WEEK2_RESULTS.md | `build_hourly_generators.py --archive <zip>`, then `walk_forward.py` | baselines |
| Missing inputs | WEEK2_RESULTS.md | `build_serving_bundle.py`, then `evaluate_missing_inputs.py` | baselines |
| Leakage check | WEEK2_RESULTS.md | `check_leakage.py` | baselines |
| Errors by condition, 3 worst days | WEEK3_ANALYSIS.md | `analyse_errors.py` | `walk_forward.py` |
| Input effects (explainability) | WEEK3_ANALYSIS.md | `explain_model.py` | `build_serving_bundle.py` |
| Chapter 6 metrics and statistical tests | MODEL_TUNING.md | `score_course_metrics.py` | `walk_forward.py` |
| Tuning (regularization, features, ensemble, sizing rule) | MODEL_TUNING.md | `tune_model.py` | `walk_forward.py` |
| Household 3 July test of the tuning | MODEL_TUNING.md, results/final_test_household_3.json | **Already run once; do not rerun.** `transfer_test.py --archive <zip>` rehearses on June | |
| Household 3 transfer | WEEK3_ANALYSIS.md | `walk_forward.py --site household_3` | baselines |
| September final test | FINAL_RESULTS.md, results/final_test_azm.json | **Already run once; do not rerun.** `final_test.py` without `--open-test-set` rehearses on August | |

Tested with Python 3.12 and 3.13. On some Windows machines the first import
of scikit-learn after installing is blocked for a moment by Smart App
Control; running the command again works.

## Project structure

Data, features, models, evaluation and serving are kept in separate folders
under `src/lebanon_energy/`:

| Folder | What it does | Main modules |
|---|---|---|
| `data/` | Read the source ZIP, prepare complete hourly data, weather, calendar, data checks | `preparation`, `audit`, `weather`, `azm_weather`, `calendar_days`, `data_checks` |
| `features/` | Model inputs known at the midnight issue time | `history`, `holidays`, `village` |
| `models/` | Baselines, Ridge, XGBoost, P90 quantile model, backtests, rolling-origin check, served bundle, exact explanations, location-only trial | `baselines`, `ridge`, `boosting`, `quantiles`, `azm_backtest`, `walk_forward`, `serving`, `explain`, `location_trial` |
| `evaluation/` | Error metrics, daily peak error, wrong-generator hours, missing-input test, leakage check, error analysis, backtest table, one-shot final test, run log | `metrics`, `peak_scores`, `generator_choice`, `missing_inputs`, `leakage`, `error_analysis`, `backtest_table`, `final_test`, `run_log` |
| `generators/` | Generator capacities, operating pattern, selection rule | `capacity`, `policy` |
| `api/` | FastAPI forecast and generator-advice service | `service` |
| `app/` | Streamlit operator page | `main` |

`scripts/` holds one command per step, `tests/` the unit tests, `config/`
the settings and decisions, `outputs/` (not in Git) every generated file,
and `results/run_log.csv` (in Git) the scores of every logged run. [DATA_PROVENANCE.md](DATA_PROVENANCE.md) documents the data.

## Current tools

- `src/lebanon_energy/data/audit.py`: inspect the original ZIP and nested workbooks
  without extracting or modifying them; report dates, columns, blanks,
  intervals, duplicate data groups, and weather metadata.
- `src/lebanon_energy/evaluation/metrics.py`: paired MAE, RMSE, maximum absolute error,
  and nMAE, with no automatically chosen acceptance threshold.
- `scripts/compare_modes.py`: compare actual paired experiment predictions
  separately for each site and target.
- `scripts/run_baselines.py`: prepare complete hourly data and evaluate the
  three approved historical baselines without scoring reserved test months.
- `scripts/verify_baseline_outputs.py`: independently reconstruct saved
  predictions and reconcile scores, coverage and issue times.
- `src/lebanon_energy/generators/policy.py`: evaluate explicitly permitted generator
  configurations using supplied usable capacities and reserve margin; flag
  infeasible cases and return tied configurations for operator choice.
- `config/`: confirmed scope and unresolved site/equipment metadata.
- `tests/`: evaluation, date-parsing, and generator-constraint checks.

- `src/lebanon_energy/generators/capacity.py` / `scripts/extract_generators.py`:
  observed maximum output of each Azm generator and the whole-hour operating
  pattern, written as the draft policy `config/azm_generators.json`.
- `src/lebanon_energy/evaluation/generator_choice.py` / `scripts/score_generator_choice.py`:
  wrong-generator hours (undersized = overload risk, oversized = wasted fuel)
  for every saved validation forecast. See [GENERATORS.md](GENERATORS.md).
- `Dockerfile`, `docker-compose.yml`: containerised FastAPI service.
- [CONTRIBUTIONS.md](CONTRIBUTIONS.md): who did what (required for submission).

Ridge/XGBoost training, saved-model verification, forecast-weather alignment
and P90 experiments are implemented. The served method was selected with the
rolling-origin check in [WEEK2_RESULTS.md](WEEK2_RESULTS.md).

## Generator rule and Docker

```powershell
.\.venv\Scripts\python.exe scripts/extract_generators.py --archive '..\Data for EECE 490 Project.zip'
.\.venv\Scripts\python.exe scripts/score_generator_choice.py
docker compose up --build
```

The first command reads Azm rows before September 1 only. The second needs
the baseline, Ridge, XGBoost and P90 runs listed below. The compose file
mounts `outputs/serving/` (the model bundle) into the API container and
`outputs/baselines_confirmed_azm/` (meter history) into the page container.
Build the bundle with the pinned versions so it unpickles in the container.

## Model experiments

The existing `.venv` is ready and selected as the default Python interpreter
in `.vscode/settings.json`. These commands reproduce the current experiments:

```powershell
.\.venv\Scripts\python.exe scripts/train_ridge.py --baseline-dir outputs/baselines_confirmed_azm --config config/ridge.json --archive '..\Data for EECE 490 Project.zip' --output-dir outputs/ridge_history_calendar
.\.venv\Scripts\python.exe scripts/prepare_weather_features.py --archive '..\Data for EECE 490 Project.zip' --sites config/sites.json --baseline-dir outputs/baselines_confirmed_azm --output-dir outputs/weather_features
.\.venv\Scripts\python.exe scripts/train_ridge.py --baseline-dir outputs/baselines_confirmed_azm --config config/ridge_weather.json --archive '..\Data for EECE 490 Project.zip' --weather-features outputs/weather_features/features.csv --output-dir outputs/ridge_weather_preliminary
.\.venv\Scripts\python.exe scripts/train_xgboost.py --baseline-dir outputs/baselines_confirmed_azm --config config/xgboost.json --archive '..\Data for EECE 490 Project.zip' --output-dir outputs/xgboost_history_calendar
.\.venv\Scripts\python.exe scripts/train_xgboost.py --baseline-dir outputs/baselines_confirmed_azm --config config/xgboost_weather.json --archive '..\Data for EECE 490 Project.zip' --weather-features outputs/weather_features/features.csv --output-dir outputs/xgboost_weather_preliminary
.\.venv\Scripts\python.exe scripts/train_quantile.py --baseline-dir outputs/baselines_confirmed_azm --sites config/sites.json --config config/quantile.json --archive '..\Data for EECE 490 Project.zip' --output-dir outputs/azm_net_p90
```

Weather experiments are preliminary, explicitly approved by the user:
publication times are unverified. The meter clock is confirmed as Lebanese
local time with summer time; instantaneous and preceding-hour radiation
values are aligned separately. Observed future weather is not a model input.

Recompute the combined comparison with:

```powershell
.\.venv\Scripts\python.exe scripts/compare_models.py --baseline-dir outputs/baselines_confirmed_azm --runs outputs/ridge_history_calendar outputs/ridge_weather_preliminary outputs/xgboost_history_calendar outputs/xgboost_weather_preliminary --output-dir outputs/model_comparison
```

Replay any Ridge or XGBoost point model run using
`scripts/verify_ridge_outputs.py --baseline-dir outputs/baselines_confirmed_azm --model-dir RUN_DIRECTORY --archive '..\Data for EECE 490 Project.zip'`.
For weather runs also pass `--weather-features outputs/weather_features/features.csv`.
The verifier name is retained for compatibility; it now checks both families.
The direct P90 run has `scripts/verify_quantile_outputs.py`.

## First baseline experiment

The user approved the complete-hour rules in `BASELINE_PROTOCOL.md`.
Azm is validated on August 2026; the other sites are validated on June 2025.
September/July remain reserved for final testing. The user confirmed Azm's
`Production` as solar PV and `Load Power` as campus load, both in kW.
Original source column names remain in the reports alongside those meanings.

```powershell
.\.venv\Scripts\python.exe scripts/run_baselines.py --archive '..\Data for EECE 490 Project.zip' --config config/baseline.json --sites config/sites.json --output-dir outputs/baselines_confirmed_azm
.\.venv\Scripts\python.exe scripts/verify_baseline_outputs.py --output-dir outputs/baselines_confirmed_azm --archive '..\Data for EECE 490 Project.zip'
```

The run saves source-unit hourly observations, every validation prediction,
and JSON scores under ignored `outputs/baselines_confirmed_azm/`. The original
pre-confirmation run is retained under `outputs/baselines/`. It does not publish data,
select a final model, or infer missing equipment details.

## Setup

The pinned dependencies were tested with Python 3.12.14 and 3.13.12. Use the
virtual environment's explicit executable; see Quick start above.

With a working Python installation, use PowerShell from the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-modeling.lock.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/audit_data.py --archive '..\Data for EECE 490 Project.zip' --output outputs/data_audit.json
```

If pip cannot reach `files.pythonhosted.org` (this happened on the AUB
network on November 10), a conda environment from Anaconda's default channel
gives the same scikit-learn 1.9.1 / numpy 2.5.4 / XGBoost 3.4.1 versions:

```powershell
conda create -n eece490 --override-channels -c defaults python=3.12 openpyxl scikit-learn py-xgboost fastapi uvicorn httpx joblib threadpoolctl tzdata pandas plotly streamlit
conda run -n eece490 python -m pip install -e . --no-deps --no-build-isolation
```

The audit reads the supplied archive directly. The large optional external
building dataset is listed but not expanded or analyzed by this command.
All audit reports are local, generated files under ignored `outputs/`.

## Comparing input modes

Once real held-out predictions exist, supply a CSV with these columns:

```text
site_id,timestamp,target,actual,history_prediction,location_prediction
```

`target` is `load` or `pv`; timestamps must include a timezone offset. Both
modes must predict the same observation, in the same unit. Repeated keys,
missing predictions and non-finite values are rejected. The command does not
verify how models were trained; holdout and issue-time provenance must be
recorded by the experiment pipeline.

```powershell
.\.venv\Scripts\python.exe scripts/compare_modes.py --predictions outputs/paired_predictions.csv --output outputs/mode_comparison.json
```

nMAE is MAE divided by mean actual, expressed as a fraction. It is undefined
when every actual value is zero. A scoring result does not itself approve the
experimental mode for use.

## Data handling

The source ZIP, local `data/`, environment files and generated outputs are
ignored by Git. No supplied measurements have been pushed to GitHub.
Publication permission must be established before sharing source data or
derived records. Original datasets must remain unchanged.

The user confirmed that the historical export belongs to Azm University at
the supplied Maps pin. The other seven sites are in **دير قانون النهر
(Deir Qanoun en Nahr)**, confirmed by the user on November 9, 2026.
The approved village weather point is approximately 33.2993 N, 35.31123 E;
exact meter coordinates remain null. Village-point weather coordinates are
stored separately in `config/sites.json`. Weather files
report grid-cell coordinates that can differ from site coordinates. Azm's
clock and radiation-interval alignment are now established; exact forecast
publication timing and original download provenance remain unverified.

The first history-based experiment follows
[the approved baseline protocol](BASELINE_PROTOCOL.md). Saved predictions,
model replay, training-only preprocessing, errors and issue times have been
independently checked. The new location-only trial uses a separate nested
site/time holdout protocol. All development runs keep the reserved test months
unscored.

## Azm weather

The two Azm weather files in the data ZIP can be re-downloaded and checked
against the supplied copies with one command (see section 5 of
[DATA_PROVENANCE.md](DATA_PROVENANCE.md)). The observed file is reproduced;
the forecast file can no longer be, so the models keep the supplied copy.

```powershell
.\.venv\Scripts\python.exe scripts/download_azm_weather.py --archive '..\Data for EECE 490 Project.zip'
```

## Village weather

Archived nominal day-ahead forecasts were cached for the nine months present
in the seven sites' approved training/validation data: August, September and
December 2024, and January-June 2025. The cache contains 6,600 unique UTC
weather hours, with no missing values in the six downloaded variables.
Dates include one-day padding before available months for later timezone
alignment. July 2025 final-test data were not requested.

```powershell
.\.venv\Scripts\python.exe scripts/download_village_weather.py --sites config/sites.json --baseline-dir outputs/baselines_confirmed_azm --output-dir outputs/weather_deir_qanoun_en_nahr
```

The script preserves API requests, responses and hashes and reuses matching
cached requests. It uses Open-Meteo's default model selection and records that
choice; a specific model/run is not reconstructed. Forecast publication timing
remains unverified. The user confirmed W units and Lebanese DST clocks.
Raw inspection found an unresolved Municipality clock conflict; the user
approved proceeding with the six household/industrial sites. See
[the inspection](VILLAGE_CLOCK_INSPECTION.md). Village weather is now joined
for the approved April-June trial, with fixed W-to-kW conversion.

## Location-only experiment

See [the full results and run commands](LOCATION_ONLY_RESULTS.md).
`scripts/prepare_village_experiment.py` creates confirmed-kW inputs and aligned
weather, `scripts/compare_location_only.py` runs the nested comparison, and
`scripts/verify_location_trial.py` independently reconstructs its results.
Fitting uses April, selection May, and evaluation June. Households 1 and 2 are
held out together; no hidden site's history enters location-only training or
features. Municipality stays pending clarification, and July remains reserved.

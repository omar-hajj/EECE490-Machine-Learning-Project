# EECE490 Machine Learning Project

May–July Azm checks and the local FastAPI demo are ready. See
[backtest results and API run instructions](AZM_BACKTEST_RESULTS.md).
The July P90 correction failed its held-out check and is not served.

Electricity-demand and solar-production forecasting for individual sites
across Lebanon, with generator planning based on each site's equipment.
Azm and the supplied household/industrial data are candidate case studies.

Baselines, Ridge, XGBoost and an initial direct net-load P90 experiment are
complete; see [the current model results](MODEL_RESULTS.md) and
[the original baseline results](BASELINE_RESULTS.md). The first approved
[location-only comparison](LOCATION_ONLY_RESULTS.md) is also complete for six
village sites. Location-only error was higher in all 12 demand/PV comparisons.
Acceptance limits remain for the user to decide; no mode is enabled automatically.

Read [the project plan](PROJECT_PLAN.md) and [initial data findings](DATA_AUDIT.md).

## Current tools

- `src/lebanon_energy/audit.py`: inspect the original ZIP and nested workbooks
  without extracting or modifying them; report dates, columns, blanks,
  intervals, duplicate data groups, and weather metadata.
- `src/lebanon_energy/evaluation.py`: paired MAE, RMSE, maximum absolute error,
  and nMAE, with no automatically chosen acceptance threshold.
- `scripts/compare_modes.py`: compare actual paired experiment predictions
  separately for each site and target.
- `scripts/run_baselines.py`: prepare complete hourly data and evaluate the
  three approved historical baselines without scoring reserved test months.
- `scripts/verify_baseline_outputs.py`: independently reconstruct saved
  predictions and reconcile scores, coverage and issue times.
- `src/lebanon_energy/generators.py`: evaluate explicitly permitted generator
  configurations using supplied usable capacities and reserve margin; flag
  infeasible cases and return tied configurations for operator choice.
- `config/`: confirmed scope and unresolved site/equipment metadata.
- `tests/`: evaluation, date-parsing, and generator-constraint checks.

- `src/lebanon_energy/generator_capacity.py` / `scripts/extract_generators.py`:
  observed maximum output of each Azm generator and the whole-hour operating
  pattern, written as the draft policy `config/azm_generators.json`.
- `src/lebanon_energy/generator_choice.py` / `scripts/score_generator_choice.py`:
  wrong-generator hours (undersized = overload risk, oversized = wasted fuel)
  for every saved validation forecast. See [GENERATORS.md](GENERATORS.md).
- `Dockerfile`, `docker-compose.yml`: containerised FastAPI service.
- [CONTRIBUTIONS.md](CONTRIBUTIONS.md): who did what (required for submission).

Ridge/XGBoost training, saved-model verification, forecast-weather alignment
and P90 experiments are implemented. Streamlit and automatic Azm weather
retrieval remain planned work. No production model has been selected.

## Generator rule and Docker

```powershell
.\.venv\Scripts\python.exe scripts/extract_generators.py --archive 'Data for EECE 490 Project (1).zip'
.\.venv\Scripts\python.exe scripts/score_generator_choice.py
docker compose up --build
```

The first command reads Azm rows before September 1 only. The second needs
the baseline, Ridge, XGBoost and P90 runs listed above. The compose file
mounts `outputs/azm_backtest/` (built by `scripts/backtest_azm.py`) into the
container; the API is then at http://localhost:8000/docs. Build that model
with the pinned versions in `requirements-serve.lock.txt` so it unpickles.

## Model experiments

The existing `.venv` is ready and selected as the default Python interpreter
in `.vscode/settings.json`. These commands reproduce the current experiments:

```powershell
.\.venv\Scripts\python.exe scripts/train_ridge.py --baseline-dir outputs/baselines_confirmed_azm --config config/ridge.json --archive 'Data for EECE 490 Project (1).zip' --output-dir outputs/ridge_history_calendar
.\.venv\Scripts\python.exe scripts/prepare_weather_features.py --archive 'Data for EECE 490 Project (1).zip' --sites config/sites.json --baseline-dir outputs/baselines_confirmed_azm --output-dir outputs/weather_features
.\.venv\Scripts\python.exe scripts/train_ridge.py --baseline-dir outputs/baselines_confirmed_azm --config config/ridge_weather.json --archive 'Data for EECE 490 Project (1).zip' --weather-features outputs/weather_features/features.csv --output-dir outputs/ridge_weather_preliminary
.\.venv\Scripts\python.exe scripts/train_xgboost.py --baseline-dir outputs/baselines_confirmed_azm --config config/xgboost.json --archive 'Data for EECE 490 Project (1).zip' --output-dir outputs/xgboost_history_calendar
.\.venv\Scripts\python.exe scripts/train_xgboost.py --baseline-dir outputs/baselines_confirmed_azm --config config/xgboost_weather.json --archive 'Data for EECE 490 Project (1).zip' --weather-features outputs/weather_features/features.csv --output-dir outputs/xgboost_weather_preliminary
.\.venv\Scripts\python.exe scripts/train_quantile.py --baseline-dir outputs/baselines_confirmed_azm --sites config/sites.json --config config/quantile.json --archive 'Data for EECE 490 Project (1).zip' --output-dir outputs/azm_net_p90
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
`scripts/verify_ridge_outputs.py --baseline-dir outputs/baselines_confirmed_azm --model-dir RUN_DIRECTORY --archive 'Data for EECE 490 Project (1).zip'`.
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
.\.venv\Scripts\python.exe scripts/run_baselines.py --archive 'Data for EECE 490 Project (1).zip' --config config/baseline.json --sites config/sites.json --output-dir outputs/baselines_confirmed_azm
.\.venv\Scripts\python.exe scripts/verify_baseline_outputs.py --output-dir outputs/baselines_confirmed_azm --archive 'Data for EECE 490 Project (1).zip'
```

The run saves source-unit hourly observations, every validation prediction,
and JSON scores under ignored `outputs/baselines_confirmed_azm/`. The original
pre-confirmation run is retained under `outputs/baselines/`. It does not publish data,
select a final model, or infer missing equipment details.

## Setup

The local `.venv` was created and verified with Python 3.12.14. Use its explicit
executable; the system-level `python` aliases are not required. For a new
machine, install Python 3.12 and create a virtual environment first. The pinned
modeling dependencies were tested with that version.

With a working Python installation, use PowerShell from the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-modeling.lock.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/audit_data.py --archive 'Data for EECE 490 Project (1).zip' --output outputs/data_audit.json
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

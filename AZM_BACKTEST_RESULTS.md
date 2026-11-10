# Azm backtests and API demo

The approved May–July checks, July split calibration and local API demo are
complete. September 2026 and village July 2025 remain unscored. Raw readings
are unchanged. These are exploratory development results.

## Earlier-month checks

Each model fits only targets before the evaluated month. Fixed settings are
Ridge alpha 1, and P90 XGBoost depth 2, 200 trees, learning rate 0.05. August
selected settings are not reused. Calendar and exact 24/168-hour lags must
be available at midnight. No weather, filling or spike removal enters this run.

| Month | Shared hours | Demand Ridge nMAE | Demand weekday nMAE | PV Ridge nMAE | PV weekday nMAE | Net P90 coverage |
|---|---:|---:|---:|---:|---:|---:|
| May | 711 | 16.7% | 19.0% | 69.1% | 64.2% | 68.9% |
| June | 685 | 28.6% | 35.6% | 51.0% | 59.4% | 63.9% |
| July | 734 | 13.5% | 16.3% | 27.6% | 34.5% | 97.0% |

nMAE is mean absolute error divided by mean actual power. Each comparison
uses the same observed hours with available model inputs and weekday profiles.
May has only 171 usable training rows because data begin in mid-April and
the features require a full week of history. Errors vary substantially by month.

## P90 adjustment

Select parameters using June and earlier training data, then refit through
June 30. Freeze the model. Use July 1–15 residuals (353 hours) to calculate
the finite-sample 90% upper order statistic. Check only July 16–31 (381 hours).

The additive correction was **−10.885 kW**. Later July coverage fell from
**96.3% to 83.5%**. Pinball loss increased from 2.504 to 2.564 (lower is better).
This adjustment failed the check and is **not served in the API**. Raw P90
coverage also varies too much to support a dependable 90% claim. Hourly
coverage guarantees neither a whole day nor instantaneous peaks. Time
dependence prevents treating the rank formula as a coverage guarantee.

## Local API

The demo supports Azm only. Demand uses Ridge with alpha selected on June,
then refitted using data before August 1. PV uses the approved weekday-average
baseline fitted before August 1. No August labels select this demo model.
Requests before the training cutoff are rejected.

Clients send midnight issue time and optional complete hourly average
readings in kW, using Lebanese local timestamps without offsets. Readings
must finish by issue time. Duplicate timestamps, nonfinite/negative readings,
future readings and ambiguous/nonexistent DST hours are rejected. This first
demo handles ordinary 24-hour days; transition days need explicit handling.

Demand uses Ridge if both lags exist, otherwise last week's matching reading,
otherwise the stored weekday profile. Each hour identifies its method,
fallback reason and latest input availability. Empty readings produce profile
forecasts. Raw negative model predictions are flagged rather than clipped.
Signed net equals total campus demand minus PV. No P90 guarantee or equipment
selection is served. Generator capacities, combinations and reserve policy
remain missing. Nationwide accuracy is not established.

Run from the project folder:

```powershell
.\.venv\Scripts\python.exe scripts/backtest_azm.py
.\.venv\Scripts\python.exe scripts/verify_azm_backtest.py
.\.venv\Scripts\python.exe -m uvicorn lebanon_energy.api.service:app --host 127.0.0.1 --port 8000
```

Open [the API documentation](http://127.0.0.1:8000/docs). `GET /health` checks
for the model file; `POST /forecast` returns 24 hourly forecasts. Minimal request:

```json
{"issue_time_local": "2026-08-01T00:00:00", "readings": []}
```

Verification writes a real-history request and response under
`outputs/azm_backtest/`. Predictions, search logs, training boundaries and
input/code/model hashes are saved there too. This is a local backend demo;
the visual dashboard and Docker deployment remain future work.

## Verification

The suite contains 59 passing tests, including request validation, model
cutoffs, explicit fallbacks, DST restrictions and calibration ranks. The
independent verification script replays July P90 and point-model API
predictions, recalculates calibration rank and coverage, checks input timing
and verifies the source ZIP hash. Final tests remain unscored.

# Week 2 results: model choice, generator advice, missing inputs

Updated November 15, 2026. Everything here uses Azm data before
September 1, 2026. **September is still unopened.** Every number comes from a
logged run (`results/run_log.csv`) and can be reproduced with the commands at
the end.

## Decision in one paragraph

The service forecasts **net load** (campus load minus PV, which is what the
generators must supply) with a **holiday-aware Ridge regression**, and sizes
the generator on an **upper estimate = forecast + the upper range of the
forecast's own errors over the last 28 days**. XGBoost did not clearly beat
Ridge, forecast weather did not help, and the XGBoost P90 model's coverage
was too unstable to size a generator on. Under the roadmap's Week 2 gate
("if XGBoost doesn't beat Ridge or the baseline clearly, keep the simpler
model and say why"), the simpler model is kept.

## How it was tested: daily rolling origin

`scripts/walk_forward_azm.py` forecasts every day from May 1 to August 31 at
midnight, with models refitted only on hours before that midnight. Settings
are fixed in advance (`config/walk_forward.json`), so no day tunes the model
that forecasts it. All methods are compared on the same 2,694 hours
(May 8 to August 31; the first week is needed to collect recent errors).
August is the validation month; May to July are the roadmap's "rolling-origin
backtests inside the training period".

### Point forecasts of net load (all months)

| Method | nMAE | Largest hourly error | Undersized hours | Oversized hours |
| --- | ---: | ---: | ---: | ---: |
| Same hour last week | 19.2% | 326 kW | 71 (2.6%) | 129 (4.8%) |
| Weekday average | 21.0% | 258 kW | 85 (3.2%) | 196 (7.3%) |
| Ridge | 16.8% | 293 kW | 65 (2.4%) | 128 (4.8%) |
| **Ridge, holiday-aware** | **16.3%** | **212 kW** | **56 (2.1%)** | 133 (4.9%) |
| Ridge, holiday-aware + forecast weather | 16.7% | 207 kW | 55 (2.0%) | 133 (4.9%) |
| XGBoost | 17.2% | 277 kW | 76 (2.8%) | 113 (4.2%) |
| XGBoost on the change from last week | 17.5% | 401 kW | 71 (2.6%) | 120 (4.5%) |

nMAE is mean absolute error divided by mean absolute net load. "Undersized"
means the generator picked from the forecast (plus the 10% reserve) could
not carry the actual hourly load; "oversized" means a smaller allowed unit
would have done. Month-by-month tables are in
`outputs/walk_forward/summary.md`.

What this shows:

- **Ridge beats both baselines and XGBoost overall**, by a modest margin.
  XGBoost is ahead in May and July and slightly in August (15.3% vs 15.7%);
  Ridge is far ahead in June (19.2% vs 25.7%), the month the load jumped.
  Neither is reliably better, so the simpler one stays.
- **Holiday handling is worth keeping.** Treating a public holiday as a
  Sunday, and not using a holiday as "last week", cuts the worst error from
  293 to 212 kW and removes 9 undersized hours. It helps in May and June
  (which contain 7 of the 9 holidays) and costs about one point of nMAE in
  July and August.
- **Forecast weather adds nothing** (16.7% vs 16.3%). It is therefore not an
  input of the served model. This matches the earlier load-only result in
  `MODEL_RESULTS.md`.
- **Modelling the change from last week** (the roadmap's idea for the
  September jump) did not help XGBoost on these months. Ridge already uses
  last week's value linearly, so it can follow a rise in level without that
  change.

### Upper estimates for sizing (target: 90% of hours at or below)

| Method | Coverage, all months | Range across months | Undersized hours | Oversized hours |
| --- | ---: | --- | ---: | ---: |
| Weekday P90 profile | 76.7% | 55% to 99% | 44 (1.6%) | 489 (18.2%) |
| XGBoost P90 | 87.9% | 79% to 97% | 44 (1.6%) | 280 (10.4%) |
| XGBoost P90 on the weekly change | 89.0% | 83% to 98% | 31 (1.2%) | 314 (11.7%) |
| Ridge + recent errors | 91.5% | 87% to 99% | 18 (0.7%) | 572 (21.2%) |
| **Holiday-aware Ridge + recent errors** | **92.1%** | **89% to 98%** | **14 (0.5%)** | 554 (20.6%) |

- "Recent errors" means: for each clock hour, take the forecast's errors at
  that hour on the previous 28 days and add their upper range (the 90%
  order statistic) to the forecast. Every error used was known at midnight.
- This is the only family that stays near 90% in every month. In June, when
  load jumped (highest 395 kW), XGBoost P90 fell to 79% and left 35
  undersized hours; the recent-error method stayed at 91% with 10. Because
  the margin is rebuilt every night from the latest errors, it widens within
  days when the model starts missing. That is the property we want for
  September.
- **The price is more oversizing**: about 21% of hours against 10% for
  XGBoost P90. It cuts overload-risk hours by two thirds (44 to 14). Whether
  that trade is right is the operator's call; the reserve margin (10%) is
  the knob.
- 90% is an empirical hourly figure, not a guarantee, and it says nothing
  about peaks inside an hour.

### Compared with what the operator actually ran

On the 2,519 hours where one generator configuration ran unchanged
(inferred practice, from the status columns):

| | Undersized | Oversized | Right-sized | Excess capacity |
| --- | ---: | ---: | ---: | ---: |
| What the operator ran | 0 (0.0%) | 1,642 (65.2%) | 877 (34.8%) | 330,292 kWh |
| Forecast rule (served method) | 9 (0.4%) | 496 (19.7%) | 2,014 (80.0%) | 56,675 kWh |

The operator never undersized but ran a larger unit than needed in two
hours out of three. The forecast rule would cut that to one in five, at the
cost of 9 hours (0.4%) where the picked unit's observed maximum was below
the actual hourly load.

Read this with care:

- "Excess capacity" is kW of unused capacity summed over hours. It is not
  litres of diesel. Converting it needs the units' fuel curves, which we do
  not have.
- Capacities are the highest outputs seen in the data, so they are lower
  bounds on the real ratings. Some "undersized" hours may be within the real
  rating.
- The operator may have reasons we cannot see (maintenance, a unit out of
  service, rotation of running hours). This still needs the school's answer.

## What the API now returns

`POST /forecast` (see `src/lebanon_energy/api/service.py`) returns, for each
of the 24 hours: load, PV and net forecasts, the upper estimate, the method
used, and a `generator` block with the configuration to run, its capacity and
the capacity required. The response also carries:

- `input_status`: `full`, `fallback` or `unavailable`, with a sentence the
  page shows as the Trust banner;
- `generator_policy`: capacities, allowed combinations, reserve margin and
  the policy's draft status.

Two rules were added to the draft policy:

- **Fallback chain when meter history is missing:** main model, then the
  same hour last week, then the stored weekday average. Each has its own
  margin. Fallback margins come from 84 days of past errors (they cannot be
  refreshed from recent data) and are never negative.
- **Minimum run of 3 hours** (`minimum_run_hours` in
  `config/azm_generators.json`): a dip to a smaller unit lasting under
  3 hours is held on the larger one. Capacity is only ever raised. In
  August this cut generator changes from 3.2 to 2.6 per day and added 9
  oversized hours. The value 3 is a placeholder for the school to set.

The served bundle (`scripts/build_serving_bundle.py`) is trained on data
before August 1, so August can be replayed honestly in the page.

## Real-world constraint: missing inputs

`scripts/evaluate_missing_inputs.py` replays every August day through the
served function, removing meter data before midnight, with and without the
fallbacks (740 observed hours):

| What is missing at midnight | Fallback | Hours with no forecast | Net nMAE | Upper coverage | Undersized | Oversized | Changes per day |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Nothing | on | 0 | 16.1% | 88.4% | 4 | 129 | 2.6 |
| Last 6 hours of meter data | on | 0 | 17.2% | 86.1% | 4 | 114 | 2.3 |
| Last 6 hours of meter data | off | 180 | 17.7% | 88.8% | 2 | 104 | |
| Last 24 hours | on | 0 | 17.7% | 85.3% | 4 | 197 | 2.8 |
| Last 24 hours | off | 692 | 21.2% | 85.4% | 0 | 2 | |
| Last 8 days, or all history | on | 0 | 19.7% | 91.2% | 4 | 218 | 4.7 |
| Last 8 days, or all history | off | 740 | | | | | |
| Weather forecast | n/a | 0 | unchanged | unchanged | unchanged | unchanged | |

- **Without fallbacks the service simply stops**: a 6-hour gap removes the
  forecast for 180 of 740 hours (every evening), a one-day gap for 692.
  Scores in the "off" rows cover only the hours that still got a forecast.
- **With fallbacks every hour gets a plan**, overload-risk hours stay at 4,
  and the cost is paid in oversizing (129 to 218 hours) and a few points of
  error (16.1% to 19.7%).
- **A missing weather forecast changes nothing**, because weather is not an
  input. That is a consequence of the finding above, not an untested claim.
  If the approved constraint requires a weather-dependent model, that model
  exists as a candidate (`ridge_holiday_weather`) and scored no better.
- The fallback margin window (84 days) was chosen after seeing August
  results with a 28-day window (coverage 67% to 71%). August is the
  validation month, so this is allowed tuning, but these August numbers are
  therefore not a clean estimate. September will be.

## Leakage check

`scripts/check_leakage.py` writes the feature table
(`outputs/features/azm_feature_table.csv`, 3,068 rows) and runs two tests on
all 137 days:

1. every input behind a feature finished at or before the midnight issue
   time: 0 violations;
2. deleting every reading from the issue time onward and rebuilding the
   day's features changes nothing: 0 violations.

## Operator page

`src/lebanon_energy/app/main.py` (Streamlit and Plotly) is the roadmap's
Tomorrow view and Trust banner: the net-load forecast with the shaded band
up to the upper estimate, a strip showing the unit to run each hour (darker
means larger), the banner, and a switch to try the missing-data cases. Past
days can overlay what actually happened. The page holds no model; it shows
what the API returns.

## What is still open

- **September final test**: not run. Freeze first (features freeze
  November 20), then score once.
- **Household 3 transfer check**: the rolling-origin script is still
  Azm-only.
- **Why panel, Backtest page, Failure gallery**: Week 3. The rolling-origin
  predictions (`outputs/walk_forward/predictions.csv`) are the data for the
  Backtest page and the 3 worst days.
- **Docker**: `Dockerfile.app` and the two-service `docker-compose.yml` are
  written but were not built on the machine used on November 15 (Docker is
  not installed there). Build them before the Week 2 gate.
- **School answers** still missing: real ratings, allowed combinations,
  reserve margin, minimum run time, academic calendar, publication
  permission.

## Reproduce

```powershell
.\.venv\Scripts\python.exe scripts/prepare_weather_features.py --archive '..\Data for EECE 490 Project.zip' --sites config/sites.json --baseline-dir outputs/baselines_confirmed_azm --output-dir outputs/weather_features
.\.venv\Scripts\python.exe scripts/walk_forward_azm.py
.\.venv\Scripts\python.exe scripts/check_leakage.py
.\.venv\Scripts\python.exe scripts/build_serving_bundle.py
.\.venv\Scripts\python.exe scripts/evaluate_missing_inputs.py
```

The rolling-origin run takes about 3 minutes. Then start the two services:

```powershell
.\.venv\Scripts\python.exe -m uvicorn lebanon_energy.api.service:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m streamlit run src/lebanon_energy/app/main.py
```

or `docker compose up --build` for both (API on port 8000, page on 8501).

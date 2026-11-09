# Location-only input comparison

The approved first trial found higher error for location-only input in all
12 demand/PV comparisons. Based on this evidence, historical meter readings
remain the recommended input for the main application. No acceptance cutoff
or production input policy was selected automatically.

This is a preliminary unseen-site experiment within Deir Qanoun en Nahr.
It does not establish performance at unseen locations across Lebanon.

## Results

Each row compares both input modes on the same 720 June 2025 hours. Values
are nMAE: average absolute error divided by average actual demand or PV.
Lower is better; these are not MAPE or percentage accuracy scores.

| Site | Target | History-based error | Location-only error |
| --- | --- | ---: | ---: |
| Household 1 | Demand | 8.0% | 38.8% |
| Household 1 | PV | 25.9% | 65.9% |
| Household 2 | Demand | 8.9% | 82.3% |
| Household 2 | PV | 22.2% | 75.6% |
| Household 3 | Demand | 49.1% | 50.0% |
| Household 3 | PV | 57.7% | 58.3% |
| Industrial 1 | Demand | 16.4% | 65.5% |
| Industrial 1 | PV | 24.5% | 79.9% |
| Industrial 2 | Demand | 88.3% | 1,142.2% |
| Industrial 2 | PV | 42.0% | 95.4% |
| Industrial 3 | Demand | 91.1% | 1,203.6% |
| Industrial 3 | PV | 51.7% | 187.2% |

Errors above 100% are possible because the average mistake can exceed the
site's average recorded demand. The industrial sources with small average
loads make an overestimate especially large under this normalization.
This is not a negative accuracy score, and no high-error site was silently
removed from the approved trial.

All six sites use the same village weather point. Those inputs do not reveal
building size, operating schedule, installed solar capacity or appliance use.
Households 1 and 2 receive identical location-only predictions for identical
dates/times within their shared holdout fold, despite different actual demand.

## What each mode receives

Location-only models receive village coordinates, known calendar information,
and nominal day-ahead weather forecasts. They receive no site identifier,
building type, equipment capacity, past target-site consumption/PV, or
normalization derived from the hidden site's actual demand.

The history-based alternative may use the site's own past readings and
calendar/weather information. Its settings and choice between ML and simple
baselines are determined using May only. June readings from earlier days can
be used for later historical lags only when already available at the midnight
forecast issue time, as in the approved operational protocol.

## How the trial was run

1. The user confirmed that all seven village sources use watts. Values were
   converted to kW with the fixed factor 0.001, without changing original files
   or using a target-site mean or capacity to scale predictions.
2. Original March files were inspected. Six sources match the reported DST
   transition; Municipality has an unresolved different gap. The user approved
   using the six consistent sources and April-June windows for this trial.
3. Forecast weather was aligned in Lebanese local time. Instantaneous fields
   use the hour start; radiation uses the hour-end value for its preceding-hour
   mean. All 2,184 April-June calendar hours have forecast features.
4. Each evaluated site was excluded completely from location-only fitting and
   setting selection. Households 1 and 2 were excluded together because of
   their known shared source data. This produced five site-group folds.
5. Models were fitted on April, settings selected on May, then refitted on
   April-May. June labels were used for final scoring of this development
   trial, not for choosing models or parameters.
6. Ridge and XGBoost candidates were considered. The history-based reference
   also considered yesterday, last-week and weekday-average baselines, selected
   using May. No input mode was accepted by an invented error threshold.

The history-based numbers differ from earlier model tables because this is
a new, stricter experiment with an April-May fitting window and May-only
selection. Earlier scores are retained in `MODEL_RESULTS.md`; they were not
overwritten. A fixed W-to-kW conversion alone does not change nMAE.

## Verification and limits

An independent checker reconstructed the unit conversion, features and
metrics, refitted the selected models from their declared pre-June data,
and replayed all saved predictions. It checked 22 selected ML artifacts,
12 paired site/target comparisons, May-only selection, source-site exclusion,
and equal location-only predictions for the grouped households.
All 53 project tests passed after the new comparison and clock/unit checks.

The original archive is unchanged, Municipality is not part of this trial,
and July's reserved test data remain unscored. Raw predictions are primary;
nonnegative clipping is recorded separately as a diagnostic.

Weather publication times remain unverified. Forecast timing is the explicitly
approved preliminary nominal `previous_day1` assumption. The dataset covers
one village, with approximate shared coordinates and limited site diversity.
The experiment therefore supports a practical warning about location-only
input here, not a universal impossibility claim or a nationwide accuracy claim.

## Reproducing the experiment

The decisions are recorded in `config/location_only.json`. From the project
folder, with the existing `.venv`:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_village_experiment.py --baseline-dir outputs/baselines_confirmed_azm --weather-dir outputs/weather_deir_qanoun_en_nahr --sites config/sites.json --config config/location_only.json --archive 'Data for EECE 490 Project (1).zip' --output-dir outputs/village_location_trial
.\.venv\Scripts\python.exe scripts/compare_location_only.py --prepared-dir outputs/village_location_trial --config config/location_only.json --archive 'Data for EECE 490 Project (1).zip' --output-dir outputs/location_only_comparison
.\.venv\Scripts\python.exe scripts/verify_location_trial.py --prepared-dir outputs/village_location_trial --result-dir outputs/location_only_comparison --baseline-dir outputs/baselines_confirmed_azm --archive 'Data for EECE 490 Project (1).zip'
```

Detailed candidate logs, model hashes, predictions and source hashes are in
the ignored local output folders. No source data or results were published.

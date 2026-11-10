# Forecasting model development results

Updated November 9, 2026. These are validation results used during model
development. September 2026 for Azm and July 2025 for the other sites remain
reserved and unscored. No production model has been selected.

## Azm University point forecasts

Errors are nMAE: average absolute error divided by average actual demand or
solar production. Lower is better. This is not MAPE or a percentage accuracy.
All methods below use the same 734 observed August hours.

| Target | Best simple baseline | Ridge history/calendar | Ridge with forecast weather | XGBoost history/calendar | XGBoost with forecast weather |
| --- | ---: | ---: | ---: | ---: | ---: |
| Campus demand | 16.6% | 15.6% | 15.6% | 16.8% | 16.8% |
| Solar PV | 36.9% | 38.3% | 39.2% | 47.0% | 45.4% |

The weather columns are preliminary experiments approved by the user. The
meter's Lebanese local clock and daylight-saving behavior are confirmed.
Weather clock and radiation-interval alignment were implemented and tested,
but exact historical publication times were not supplied. Nominal one-day
forecast timing must not be presented as verified publication availability.

Ridge gave a modest demand improvement here. Neither tested ML method beat
the simple baseline for Azm solar PV. XGBoost did not establish an advantage
over Ridge for this dataset and feature set. This is useful evidence rather
than a reason to discard unfavorable runs or claim ML always helps.

## Other sites

History/calendar models were also trained separately for all seven other
sites. Every row uses the same 720 June observations for all listed methods.
At the time of these runs the village location was unknown, so no weather
location was invented. The user later identified Deir Qanoun en Nahr and
approved a representative weather point; weather is cached but these model
results have not been retrained with it.

| Site | Target | Best simple baseline | Ridge | XGBoost |
| --- | --- | ---: | ---: | ---: |
| Household 1 | Demand | 8.0% | 14.9% | 8.5% |
| Household 1 | PV | 25.9% | 28.4% | 28.0% |
| Household 2 | Demand | 8.9% | 15.2% | 11.4% |
| Household 2 | PV | 20.1% | 26.5% | 24.7% |
| Household 3 | Demand | 50.7% | 46.3% | 45.7% |
| Household 3 | PV | 46.9% | 41.8% | 43.3% |
| Industrial 1 | Demand | 16.3% | 15.9% | 18.1% |
| Industrial 1 | PV | 24.5% | 25.4% | 25.8% |
| Industrial 2 | Demand | 86.2% | 87.4% | 95.8% |
| Industrial 2 | PV | 32.5% | 32.6% | 33.4% |
| Industrial 3 | Demand | 82.2% | 83.4% | 90.6% |
| Industrial 3 | PV | 47.4% | 49.4% | 45.9% |
| Municipality | Demand | 102.6% | 98.1% | 95.8% |
| Municipality | PV | 83.1% | 88.0% | 84.5% |

These original runs are per-site history-using models. At the time, village
units were unconfirmed; the user later confirmed W. Their original numerical
scores are retained. A separate confirmed-kW six-site unseen-site experiment
is now documented in `LOCATION_ONLY_RESULTS.md`. Duplicated Household 1/2
months prevent treating all source records as independent evidence.

## Daily peak error (added November 10, 2026)

The roadmap asks for "MAE, RMSE, peak error". The tables above report the
largest error in any single hour. Since the generator must cover each day's
highest load, we also score **daily peak error**: for each day, the forecast
daily maximum minus the actual daily maximum. A negative value is an
under-forecast, the overload-risk direction. All methods use the same hours,
and only days with all 24 hours are scored. Reproduce with
`scripts/score_daily_peaks.py`; results are in `outputs/peak_scores/`.

**Azm, August 2026 (load, kW, 22 complete days):**

| Method | nMAE | Largest hourly error | Daily peak error | Under-forecast days | Peak hour off |
| --- | ---: | ---: | ---: | ---: | ---: |
| Yesterday | 28.2% | 235 | 111 | 9 of 22 | 3.3 h |
| Last week | 17.3% | 210 | 48 | 15 of 22 | 2.8 h |
| Weekday average | 16.6% | 207 | **37** | 12 of 22 | 2.8 h |
| Ridge | **15.6%** | **189** | 50 | 12 of 22 | **1.8 h** |
| XGBoost | 16.8% | 196 | 54 | 14 of 22 | 2.7 h |

**Household 3, June 2025 (load, W, 30 complete days):**

| Method | nMAE | Largest hourly error | Daily peak error | Under-forecast days | Peak hour off |
| --- | ---: | ---: | ---: | ---: | ---: |
| Yesterday | 55.2% | 2,902 | 672 | 18 of 30 | 3.4 h |
| Last week | 53.6% | 3,390 | **658** | 18 of 30 | 3.1 h |
| Weekday average | 50.7% | 3,157 | 1,233 | 29 of 30 | **2.5 h** |
| Ridge | 46.3% | **2,765** | 839 | 27 of 30 | 3.2 h |
| XGBoost | **45.7%** | 3,258 | 947 | 26 of 30 | 3.0 h |

The best method depends on the metric. At Azm, the weekday average predicts
the size of the daily peak best, while Ridge has the smallest worst hour and
gets the peak's timing closest. At Household 3, the weekday average
under-forecasts the peak on 29 of 30 days, because averaging smooths a
home's irregular spikes. The ML models also under-forecast most peaks there.
A school's regular timetable makes averages work; a home's does not.
Validation results only; final test months unscored.

## Direct P90 estimate of the remaining requirement

The user confirmed that `Load Power` is total campus demand including demand
served by solar. The derived target is therefore `Load Power - Production`,
in kW. Signed values are retained; negative values indicate an arithmetic
surplus, without assuming actual export, storage or control behavior.

A separate XGBoost quantile model was fitted directly to this target, using
past signed net readings and calendar features. The intended upper quantile
is P90, as specified by the roadmap. Hyperparameters were selected by
validation pinball loss, not point-forecast MAE. No weather was used.

- The fitted upper estimate covered **85.3%** of 734 validation hours.
- A training-only weekday/hour empirical P90 baseline covered **74.5%**.
- The fitted model has not demonstrated its intended 90% coverage and needs
  further calibration/evaluation before use in an operating policy.
- P90 concerns individual hourly averages. It does not guarantee an entire
  day or protect against instantaneous peaks.
- This does not subtract separate P90 forecasts of demand and PV, which
  would not generally produce a P90 forecast of net demand.

The user confirmed parallel generator operation is possible. Actual usable
capacities, permitted combinations and reserve margin remain unknown. No
real generator recommendation has been generated and observed peaks were
not substituted for equipment ratings.

## Data diagnostics

The approved complete-hour rules, zeros, spikes and constant readings were
retained. Diagnostics flag patterns for investigation; they do not prove
sensor errors and did not trigger data corrections.

- Industrial 2 June demand has median 0.0336 source units and a maximum of
  911, indicating a very uneven recorded series.
- Industrial 3 June demand has median 3.085 and a maximum of 792.5 source units.
- Municipality June demand has zero readings in 17.8% of its complete hours,
  compared with no zero complete hours in the training period.
- Household 3 mean recorded demand increased from about 408.0 training source
  units to 606.0 validation source units.

Further investigation must distinguish real operational changes from data
issues. No files were excluded because their model scores were unfavorable.

## Method and reproducibility

Each site/target model uses exact 24-hour and 168-hour lag lookups plus a
one-hot hour-of-week feature. Missing lag inputs are not filled or bridged.
Inputs must be available at the midnight forecast issue time. Preprocessing
is fitted only on training rows. Weather uses forecast values, never observed
future weather, with different alignment for instantaneous and radiation fields.

Ridge tested five regularization strengths. XGBoost tested four fixed
depth/tree-count combinations. Every candidate and selected validation score
is logged. Validation tuning means these numbers are development estimates;
the untouched final tests must be evaluated after the design is frozen.

Raw model predictions are the primary point-comparison outputs. Negative
predictions and nonnegative clipping diagnostics are recorded separately;
no clipping was silently applied to obtain these tables.

The local Python environment and VS Code interpreter setting are ready.
Exact installed versions are recorded in `requirements-modeling.lock.txt`.
Models, inputs, configurations, predictions and source hashes are logged
under ignored `outputs/`. The original ZIP remains unchanged.

All 47 tests passed. Saved point-model predictions and preprocessing were
independently replayed, including all 18 new XGBoost models. The direct P90
target, predictions, pinball losses, measured coverage and input timing were
also independently reconstructed. Package dependency checks passed.

Run instructions are in `README.md`. Detailed evidence is under:

- `outputs/model_comparison/`: recomputed common-hour comparison.
- `outputs/ridge_history_calendar/` and `outputs/ridge_weather_preliminary/`.
- `outputs/xgboost_history_calendar/` and `outputs/xgboost_weather_preliminary/`.
- `outputs/azm_net_p90/`: signed net-load upper-estimate experiment.
- `outputs/weather_features/` and `outputs/source_diagnostics.json`.

## Remaining work

May–July Azm backtests and split July calibration are now complete; see
`AZM_BACKTEST_RESULTS.md`. The correction failed its later-period check and
is not served. A local FastAPI demo implements the approved point-forecast
and fallback policy. Investigate uncertainty failures, confirm equipment
information and source metadata, then build Docker and the operator interface
without consuming the final test prematurely. The village is Deir Qanoun en Nahr;
the first six-site location-only comparison is complete under a separately
approved held-out-site/time protocol. Municipality's clock remains unresolved.
The trial does not establish nationwide generalization. No app or API is
deployed yet.

## References

- [XGBoost parameters and quantile objective](https://xgboost.readthedocs.io/en/stable/parameter.html).
- [Scikit-learn Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html).
- [Open-Meteo time and radiation semantics](https://open-meteo.com/en/docs).

# Final test: Azm, September 2026

Run once on November 15, 2026 with `scripts/final_test.py --open-test-set`,
from commit `37efb42` (settings and generator policy as committed). The full
record is `results/final_test_azm.json`; the script refuses to run again
while that file exists. Nothing was tuned after seeing these numbers.

September was the reserved month: never read before this run. Each day was
forecast at midnight by models fitted on earlier hours only, exactly as in
the May–August rolling-origin check (`WEEK2_RESULTS.md`).

## What September looked like

- Mean net load **143 kW**, against 90 kW from May to August.
- Highest hour **462 kW**, above anything in training (395 kW) and above the
  largest single generator (413 kW observed), so some hours needed two
  units in parallel.
- 617 of 720 hours are scored. The other 103 lack a complete meter hour or
  an input one of the compared methods needs; all methods are scored on the
  same 617 hours.

## Results table

| Point forecast | Error (nMAE) | Largest error | Undersized hours | Oversized hours |
| --- | ---: | ---: | ---: | ---: |
| Same hour last week (best baseline) | 22.4% | 285 kW | 58 (9.4%) | 54 (8.8%) |
| Weekday average | 37.7% | 299 kW | 130 (21.1%) | 0 (0.0%) |
| Ridge | 21.0% | 233 kW | 64 (10.4%) | 49 (7.9%) |
| **Ridge, holiday-aware (served)** | **20.2%** | **231 kW** | 60 (9.7%) | 52 (8.4%) |
| XGBoost | 21.0% | 257 kW | 67 (10.9%) | 37 (6.0%) |
| XGBoost on the change from last week | 21.4% | 261 kW | 63 (10.2%) | 43 (7.0%) |

| Upper estimate used for sizing (target 90%) | Coverage | Undersized hours | Oversized hours |
| --- | ---: | ---: | ---: |
| Weekday P90 profile | 53.6% | 52 (8.4%) | 40 (6.5%) |
| XGBoost P90 | 80.4% | 43 (7.0%) | 156 (25.3%) |
| XGBoost P90 on the weekly change | 85.1% | 29 (4.7%) | 181 (29.3%) |
| Ridge + recent errors | 88.2% | 19 (3.1%) | 285 (46.2%) |
| **Holiday-aware Ridge + recent errors (served)** | **88.7%** | **15 (2.4%)** | 295 (47.8%) |

"Undersized" means the generator picked (with the 10% reserve) could not
carry the actual hourly load; "oversized" means a smaller allowed
configuration would have done.

## What held and what did not

**Held:**

- The served method was the best of those compared on every count that
  matters for safety: lowest error, coverage closest to 90%, fewest
  undersized hours.
- The ranking chosen on May–August carried over to the unseen month. Ridge
  again matched or beat XGBoost; the weekday average, which cannot follow a
  change of level, collapsed (37.7%).
- Sizing on a point forecast is unsafe: every point method undersized in
  about 10% of hours. The upper estimate cut that to 2.4%.

**Did not hold:**

- **Everything got worse than on validation.** Error rose from 15.7%
  (August) to 20.2%, undersized hours from 0.5% to 2.4%, and oversized
  hours from 15.5% to 48% (all against August).
- **The first week failed**, as predicted in `WEEK3_ANALYSIS.md`:

| Days | Model error | Baseline error | Hours above the upper estimate | Undersized hours |
| --- | ---: | ---: | ---: | ---: |
| 1–7 | 28.9% | 36.7% | 34.1% | 14 |
| 8–14 | 17.3% | 18.9% | 4.9% | 0 |
| 15–21 | 17.1% | **14.7%** | 1.5% | 0 |
| 22–30 | 16.4% | 17.6% | 2.5% | 1 |

  14 of the 15 undersized hours fall in the first seven days, when term
  started and the model had only quiet August days to learn from. From day
  8 the margin had widened and there was one undersized hour in three
  weeks.
- **Then it over-corrected.** After the first-week misses entered the
  28-day error window, the margin stayed wide: only 1.5% to 4.9% of hours
  exceeded the upper estimate (target 10%), and that is why oversized hours
  reached 48%. The margin reacts within days but forgets slowly.
- **Working hours are the weak spot.** On weekdays from 07:00 to 16:59 the
  forecast was 31 kW low on average and 22.6% of hours exceeded the upper
  estimate; outside those hours, 6.5%.
- In the third week "same hour last week" beat the model (14.7% against
  17.1%), as it did in July: once the weeks repeat, repetition wins.

### Three worst days

| Day | Model error | Baseline error | What the data shows |
| --- | ---: | ---: | --- |
| Mon 14 Sep | 56 kW | 28 kW | Peak 462 kW against 262 kW forecast, the month's highest hour; 201 kW short at 07:00. |
| Tue 1 Sep | 47 kW | 51 kW | First day of the jump: peak 282 kW against 137 kW forecast; 12 hours above the upper estimate. |
| Fri 4 Sep | 43 kW | 52 kW | Peak 395 kW against 256 kW forecast; 7 hours above the upper estimate. |

All three are under-forecasts at the morning switch-on (07:00–08:00).

## Final recommendation

- **Is ML worth it over the baseline here?** Yes, but for the calibrated
  upper estimate rather than for accuracy. The forecast is only about two
  points better than "same hour last week" (20.2% against 22.4%). The
  upper estimate is what cuts overload-risk hours from about 10% to 2.4%,
  and no baseline provides one.
- **Why this level of complexity?** XGBoost was no better on the test month
  either (21.0%), and its P90 covered only 80%. The simpler model is the
  right one for 4.5 months of data.
- **When it should not be used:**
  - in the first week after a change of regime, such as the start of term.
    Here it undersized 14 hours in seven days. The operator should stay on
    the larger unit until the banner and the recent days look normal;
  - as an automatic switch, at any time;
  - when the Trust banner is not green.
- **What it costs:** in a month like September the rule oversizes about
  half the time. That is still below the 65% seen in the operator's own
  practice from May to August, but the September comparison with the
  operator was not computed, so we do not claim a saving for September.

## Limits of this test

- One month, one site. 103 of 720 hours could not be scored.
- Generator capacities are the highest outputs observed before September,
  not ratings. Some "undersized" hours may be within the real ratings.
- The operator's actual September choices were not analysed.
- Ideas this test suggests, **not tried, because the test set is now
  used**: a shorter or weighted error window so the margin relaxes faster;
  a "term starts" calendar flag; a 06:00 re-forecast using the morning's
  first readings. Any of these would need new unseen data to evaluate.

## Reproduce the analysis (not the test)

The test itself must not be rerun. These read its saved predictions:

```powershell
.\.venv\Scripts\python.exe scripts/analyse_errors.py --predictions outputs/final_test/predictions.csv --weather-features none --output-dir outputs/final_test/error_analysis
.\.venv\Scripts\python.exe scripts/build_backtest_table.py --predictions outputs/final_test/predictions.csv --output outputs/final_test/backtest.csv
```

# Week 3 analysis: errors, explanations, transfer, Responsible ML

Updated November 15, 2026. Everything here uses data before the reserved
test months (Azm September 2026, Household 3 July 2025) and was written
**before** the September test. The test has since been run once; its
results, and how the expectations below held up, are in
[FINAL_RESULTS.md](FINAL_RESULTS.md). Household 3's July remains unopened. Model choice and the
missing-input test are in [WEEK2_RESULTS.md](WEEK2_RESULTS.md).

## 1. Error analysis (Azm)

`scripts/analyse_errors.py` scores the served forecast (holiday-aware Ridge
on net load) on the 2,696 rolling-origin hours from May 8 to August 31,
against the best baseline (same hour last week). Bias is forecast minus
actual.

| Group | Hours | Mean load | Model nMAE | Baseline nMAE | Bias | Hours above the upper estimate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All hours | 2,696 | 90 kW | 16.3% | 19.1% | −1.5 kW | 7.9% |
| May | 545 | 80 kW | 17.8% | 19.5% | −8.4 kW | 9.7% |
| June | 683 | 108 kW | 19.2% | 27.5% | −4.1 kW | 8.9% |
| July | 734 | 83 kW | 12.3% | **10.9%** | +4.7 kW | 2.0% |
| August | 734 | 87 kW | 15.7% | 17.3% | −0.2 kW | 11.3% |
| Weekdays | 1,733 | 98 kW | 16.6% | 18.8% | −0.2 kW | 8.8% |
| Weekends | 774 | 76 kW | 15.5% | **14.8%** | −3.2 kW | 6.3% |
| Public holidays | 189 | 76 kW | 15.9% | 41.5% | −6.9 kW | 5.8% |
| Day after a holiday | 142 | 88 kW | 20.3% | 22.9% | −3.2 kW | 8.5% |
| Working hours (Mon–Fri 07:00–16:59) | 722 | 116 kW | 21.6% | 24.2% | +0.6 kW | 7.3% |
| All other hours | 1,974 | 80 kW | 13.5% | 16.5% | −2.3 kW | 8.1% |
| Hot days (forecast peak above 28.1 °C) | 1,374 | 86 kW | 14.4% | 14.9% | +2.6 kW | 6.8% |
| Mild days | 1,322 | 94 kW | 18.1% | 23.1% | −5.8 kW | 8.9% |

What this says:

- **The error is in the working day, not the night.** From 20:00 to 04:00
  the error is 6% to 9%; from 06:00 to 12:00 it is 22% to 30%, worst at
  06:00 (30%), when the campus switches on. That is exactly when the
  generator choice matters.
- **Holidays are where the model earns most over the baseline**: 15.9%
  against 41.5%, because "last week" is a normal working day.
- **The model does not always win.** In July and at weekends "same hour
  last week" is slightly better. July was a very regular month, and a model
  cannot beat repetition when the week simply repeats.
- **Heat is not the problem.** Hot days are forecast better than mild ones.
  The mild days are mostly May and June, when the term-time load was
  changing; this agrees with the finding that forecast weather adds nothing.
- **The upper estimate is even across the day.** Between 5% and 11% of
  hours exceed it at every hour of the day, because the margin is computed
  per clock hour. August (11.3%) is the month it ran slightly short.

### Three worst days

| Day | Model error | Baseline error | What the data shows |
| --- | ---: | ---: | --- |
| Tue 23 June | 50 kW | 12 kW | Over-forecast: peak 117 kW against 311 kW forecast. The campus ran 23% below a typical Tuesday, and the Tuesday before was a public holiday (Hijri New Year). The baseline copied that quiet holiday and happened to be right. |
| Thu 20 August | 42 kW | 51 kW | Under-forecast: peak 268 kW against 147 kW forecast, 64% above a typical Thursday; 13 hours above the upper estimate. The highest load of August, with no holiday or pattern to announce it. |
| Mon 13 July | 28 kW | 21 kW | Over-forecast: peak 137 kW against 226 kW forecast; the day ran 26% below a typical Monday. |

- June 23 is one of the three unexplained quiet weekdays already listed in
  `DATA_PROVENANCE.md` (section 4). It is probably a school closure day; the
  academic calendar would fix it. It costs fuel (oversizing), not safety.
- **August 20 is the dangerous kind**: a sudden high day. Nothing known at
  midnight predicted it, and the margin did not cover it. This is the
  honest limit of a history-based forecast, and the reason the operator
  keeps the final say (section 4).
- These explanations state what the data shows. They are not confirmed
  causes.

## 2. Explainability

Ridge is linear, so every forecast splits **exactly** into the average
level plus one effect per input (`src/lebanon_energy/models/explain.py`).
No approximation such as SHAP is needed: average + effects = forecast.

For the served model (trained before August 1):

- Each extra kW at the same hour **yesterday** adds 0.51 kW to the forecast.
- Each extra kW at the same hour **last week** adds 0.25 kW.
- The **time of week** (168 hour-of-week levels) supplies the rest.

Average size of each input's effect:

| Input | All hours | At each day's peak hour |
| --- | ---: | ---: |
| Same hour yesterday | 10.7 kW | 24.1 kW |
| Time of week | 8.4 kW | 19.6 kW |
| Same hour last week | 5.6 kW | 13.2 kW |
| Yesterday was a holiday | 1.2 kW | 1.2 kW |

**Peak hours are driven mostly by yesterday's load at the same hour.** That
is also the model's weakness: on the highest hour in the data (June 10,
08:00, actual 395 kW) the forecast was 307 kW = 89 average + 148 from
yesterday (377 kW) + 37 from last week (239 kW) + 33 from the time of week.
The model follows a rising level within a day, and lags behind it on the
first day.

The API returns these effects for the peak hour of every plan
(`peak_drivers`), and the page shows them in the **Why panel**.

## 3. Robustness and distribution shift

- **The known risk** is September: the roadmap notes weekday mornings near
  500 kW, above anything in training (highest 395 kW). This has not been
  measured yet because September is unopened.
- **June is the rehearsal we have.** Load jumped in June (highest 395 kW
  against 211 kW in May). The XGBoost P90 fell to 79% coverage with 35
  undersized hours; the served method held 91% with 10. The margin is
  rebuilt every night from the last 28 days of errors, so it widens within
  days of the model starting to miss.
- **Why Ridge and not trees under shift:** a tree cannot predict above the
  largest value it was trained on. Ridge extrapolates linearly from
  yesterday and last week. Modelling the change from last week was tested
  for XGBoost and did not help.
- **What will still go wrong:** the first days of a jump. The model needs
  one day of high readings before "yesterday" pulls it up (June 10 above),
  and the margin needs several days to widen. Expect undersized hours in
  the first week of September.
- **Missing inputs** are covered in `WEEK2_RESULTS.md`: with fallbacks every
  hour gets a plan and overload-risk hours stay at 4 in August; the cost is
  oversizing.

## 4. Human oversight

- **The operator decides.** The service gives advice with its reasons (Why
  panel), its confidence (the band), and a plain statement of what was
  missing (Trust banner). It switches nothing.
- **The two errors are not equal.** An under-forecast can overload a
  generator: a trip, a blackout on campus, possible damage. An
  over-forecast runs a larger unit than needed and wastes diesel. The
  system is therefore tilted toward oversizing: it sizes on the upper
  estimate, adds a 10% reserve, and holds the larger unit through short
  dips.
- **What that tilt costs and buys** (May to August): 14 undersized hours
  in 2,694 (0.5%) and 554 oversized (20.6%), against 0 and 65% for what the
  operator actually ran. The rule saves capacity by accepting a small
  overload risk the operator currently does not take. Whether 0.5% is
  acceptable is the school's decision, not ours.
- **When the operator should overrule it:** amber or red banner; a known
  event the model cannot see (exams, a closure, a function); the first
  days of term; a unit out of service.
- **What is not automated:** the reserve margin, the minimum run time and
  the allowed combinations are placeholders until the school sets them.

## 5. Transfer check: Household 3

Same pipeline, same fixed settings, no retuning
(`scripts/walk_forward.py --site household_3`): 5,632 hours from
August 24, 2024 to June 30, 2025, load in watts. There are no generators at
a home, so only the forecast and its upper estimate are scored.

| Method | nMAE |
| --- | ---: |
| Same hour last week | 54.0% |
| Weekday average | 63.5% |
| Ridge, holiday-aware | 46.2% |
| XGBoost | **43.1%** |

| Upper estimate (target 90%) | Coverage, all months | Range across months |
| --- | ---: | --- |
| Weekday P90 profile | 96.0% | 81% to 100% |
| XGBoost P90 | 91.5% | 82% to 97% |
| Holiday-aware Ridge + recent errors | 91.8% | 87% to 96% |

- **What transfers:** the method beats both baselines at a second, very
  different site without any retuning, and the recent-error margin again
  stays closest to 90% across months.
- **What does not:** the point forecast is poor in absolute terms (46%
  against 16% at Azm). One home's load is a few appliances switching at
  irregular times; a school of hundreds of people averages out. No
  day-ahead model should be expected to forecast a single home's hourly
  load well.
- **The model ranking does not transfer:** XGBoost is better than Ridge
  here (43.1% against 46.2%). "Keep the simpler model" is an Azm conclusion,
  not a general one.
- Holiday handling does nothing at a home (46.2% against 46.3%), as
  expected: it encodes a school's behaviour.

## 6. Limitations

- **One school, 4.5 months of data** (April 16 to August 31, before the
  test month). No autumn, winter or full term is in the training data.
- **Served load, not demand.** The meter records what the generators and PV
  delivered. If load was shed or a unit tripped, true demand was higher and
  we cannot see it.
- **PV is not modelled from the sun.** PV output follows the load more than
  the weather here (it appears to be curtailed), so net load is forecast
  directly. If the PV control changes, the model is wrong until it relearns.
- **Capacities are observed maxima, not ratings**, taken from data before
  September. "Undersized" may overstate the risk; "right-sized" assumes the
  unit can run at its observed maximum for an hour.
- **Hourly averages.** Peaks inside the hour, starting currents, switching
  time and minimum loading are not modelled.
- **Excess capacity is not fuel.** Without fuel curves we cannot state
  litres or money saved.
- **Current practice is inferred** from status columns, not confirmed.
- **Three quiet days are unexplained** and the school calendar is missing.
- **Weather timing is nominal.** Forecast weather was tested with nominal
  day-ahead availability; it did not help, so nothing served depends on it.
- **August was used for choices** (the fallback margin window, the method).
  Only September will be a clean estimate.

## 7. Final test: procedure (run on November 15; see FINAL_RESULTS.md)

`scripts/final_test.py` is the only code that reads September. It runs the
same rolling-origin procedure, settings and draft policy as above and
scores September once.

```powershell
# Rehearsal on August; reads nothing from September:
.\.venv\Scripts\python.exe scripts/final_test.py --archive '..\Data for EECE 490 Project.zip'
# The real run, once, after the November 20 freeze:
.\.venv\Scripts\python.exe scripts/final_test.py --archive '..\Data for EECE 490 Project.zip' --open-test-set
```

The real run writes `results/final_test_azm.json` and refuses to run again
while that file exists. Before running it: freeze `config/walk_forward.json`
and `config/azm_generators.json`, and commit.

### Recommendation before the test (the final one is in FINAL_RESULTS.md)

September confirmed the two main expectations written here: the first week
of term produced the undersized hours (14 of 15), and the ML value lies in
the upper estimate rather than in accuracy. It added one finding: after the
first-week misses the margin stayed too wide for the rest of the month.

- **Is ML worth it over the baseline at Azm?** Modestly for accuracy
  (16.3% against 19.1%), clearly on holidays (15.9% against 41.5%), and
  most of all for the calibrated upper estimate, which no baseline
  provides. The value is in sizing safely, not in a better average.
- **When not to use it:** in the first week after a change of regime
  (start of term); on days with a known event; when the banner is not
  green; and never as an automatic switch.
- **Why not a more complex model:** XGBoost was not reliably better on
  4.5 months of data and cannot extrapolate. No graph model: the sites share
  no meaningful relationship structure.

## Reproduce

```powershell
.\.venv\Scripts\python.exe scripts/walk_forward.py
.\.venv\Scripts\python.exe scripts/walk_forward.py --site household_3
.\.venv\Scripts\python.exe scripts/analyse_errors.py
.\.venv\Scripts\python.exe scripts/build_backtest_table.py
.\.venv\Scripts\python.exe scripts/build_serving_bundle.py
.\.venv\Scripts\python.exe scripts/explain_model.py
```

The Household 3 run takes about 20 minutes; the others a few minutes or less.

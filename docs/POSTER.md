# Poster content (draft)

Draft text for the six panels the announcement asks for. Every number is
from a logged run before September 2026 (`results/run_log.csv`); sources are
given under each panel. Replace anything marked **[TEAM]** before printing.

**Title:** Which generator tomorrow? Day-ahead load forecasting for a
generator-powered campus

**Team:** [TEAM: names] · EECE 490, Fall 2026–27 · Path A

---

## 1. Problem and intended user

- Azm's campus runs on its own diesel generators almost all the time. In
  our data, utility power was never on.
- It has four units of very different size: observed peaks of 146, 237,
  315 and 413 kW.
- Each hour someone must choose which unit runs. Too small risks an
  overload and a blackout. Too large burns diesel at low efficiency.
- **Today the choice is made without a forecast.** From the status columns,
  the unit running was larger than needed in **65% of hours**, and never
  too small. [TEAM: confirm with the school how units are chosen.]
- **User:** the facility or generator operator.
- **Decision we support:** which generator to run in each hour of tomorrow.

*Source: GENERATORS.md; WEEK2_RESULTS.md, "Compared with what the operator
actually ran".*

## 2. Baseline strategy (no ML)

- Same hour yesterday.
- Same hour last week.
- Average for that weekday and hour.

Best baseline on net load, May to August: **same hour last week, 19.2%
error**. Baselines give a single number, with no statement of how wrong it
might be.

*Source: WEEK2_RESULTS.md, point-forecast table.*

## 3. ML approach

- **Target:** net load (campus load minus solar) for each of the next 24
  hours, issued once at midnight.
- **Model:** Ridge regression on yesterday's and last week's load at the
  same hour, the hour of the week, and public holidays.
- **Upper estimate for sizing:** forecast + the upper range of the
  forecast's own errors at that hour over the last 28 days. About 9 hours
  in 10 stay below it.
- **Rule:** run the smallest allowed generator set that covers the upper
  estimate plus a 10% reserve.
- **Also tested and not kept:** XGBoost (17.2% against Ridge 16.3%),
  forecast weather (no gain), an XGBoost P90 model (coverage swung from 79%
  to 97% by month).
- **No leakage:** every input is known at midnight; checked on all 137 days
  with 0 violations.

*Source: WEEK2_RESULTS.md.*

## 4. Evaluation plan and metrics

- **Split, fixed before modelling:** train April 16 to July 31, validate
  August, test September. September is opened once, at the end.
- **Rolling origin:** every day from May to August is forecast at midnight
  by a model fitted on earlier data only.
- **Metrics tied to the decision:**
  - error of the forecast (MAE as a share of mean load);
  - coverage of the upper estimate (target 90%);
  - **wrong-generator hours**: undersized (overload risk) and oversized
    (wasted fuel).

| May to August, 2,694 hours | Error | Undersized hours | Oversized hours |
| --- | ---: | ---: | ---: |
| What the operator ran (2,519 hours) | n/a | 0.0% | 65.2% |
| Best baseline, last week | 19.2% | 2.6% | 4.8% |
| Ridge forecast alone | 16.3% | 2.1% | 4.9% |
| **Ridge + upper estimate (served)** | 16.3% | **0.5%** | 20.6% |

A forecast alone is too risky to size on (2 to 3% of hours undersized). The
upper estimate cuts that to 0.5% and still oversizes three times less often
than current practice.

*Source: WEEK2_RESULTS.md. The operator row covers the 2,519 hours where
one configuration ran unchanged.*

## 5. Real-world constraint: missing inputs

What if the meter feed is late or down at midnight?

| Missing at midnight (August) | Without fallback | With fallback |
| --- | --- | --- |
| Last 6 hours of meter data | no forecast for 180 of 740 hours | every hour planned; error 17.2% |
| Last 24 hours | no forecast for 692 hours | every hour planned; error 17.7% |
| All history | no forecast at all | every hour planned; error 19.7% |

- Fallback chain: main model, then last week's reading, then the weekday
  average, each with its own safety margin.
- Overload-risk hours stay at 4 in every case; the cost is more oversizing.
- The page tells the operator which case applies (green or amber banner).
- A missing weather forecast has no effect: weather is not an input.

*Source: WEEK2_RESULTS.md, "Real-world constraint".*

## 6. Deployment plan

- **API:** FastAPI in Docker. `POST /forecast` returns 24 hourly forecasts,
  the upper estimate, the generator to run, the reasons for the peak, and
  what was missing.
- **Operator page:** Streamlit. Tomorrow's plan with the band and the
  hour-by-hour generator strip, a Why panel, any past day replayed, and the
  three worst days.
- **Human oversight:** the system advises; the operator decides.
- **Reproducible:** pinned versions, one command per results table, every
  score logged.

## Known limits (small print)

One campus and 4.5 months of data. Generator capacities are the highest
outputs observed, not confirmed ratings. Oversizing is measured in unused
capacity, not litres of diesel. September, where load is higher than
anything in training, is not yet evaluated.

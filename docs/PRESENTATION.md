# Final presentation: 5-minute outline and Q&A preparation (draft)

Seven slides, about 40 seconds each. Numbers are from logged runs before
September 2026, except slide 5, which is the September final test
(`FINAL_RESULTS.md`). Team: Omar El Hajj, Houssein Karnib, Sami Marouni.

## Slides

**1. The decision (0:00–0:35)**
- Azm runs on four diesel generators of 146 to 413 kW. Every hour someone
  picks one.
- Too small: overload. Too large: wasted diesel.
- Today there is no forecast. The unit running was larger than needed in
  65% of hours.
- Say: "We forecast tomorrow's load and recommend the generator for each
  hour."

**2. Data and split (0:35–1:10)**
- Five-minute readings, April 16 to September 30, 2026, averaged to hours.
- Train to July 31, validate August, test September, fixed before any
  modelling.
- Every input is known at midnight: 0 leakage violations in 137 days.
- One second site, Household 3, to check the method transfers.

**3. Baselines and model (1:10–1:55)**
- Baselines: yesterday, last week, weekday average. Best: last week, 19.2%.
- Ridge with holidays: 16.3%. XGBoost: 17.2%. Forecast weather: no gain.
- Say: "XGBoost was not reliably better on 4.5 months of data, so we kept
  the simpler model."

**4. The part that matters: sizing safely (1:55–2:40)**
- A forecast alone undersizes the generator in 2% of hours.
- We add the upper range of the model's own errors over the last 28 days.
  Coverage stayed between 89% and 98% in every month.
- Undersized hours fall to 0.5%; oversized hours are 21%, against 65% for
  current practice.
- Show the Tomorrow view: band, generator strip, Why panel.

**5. September: the test (2:40–3:20)**
- September was never seen: mean load 143 kW against 90 kW before, peak
  462 kW against 395 kW in training.
- Error 20.2% against 22.4% for the baseline. Coverage 88.7% (target 90%);
  XGBoost P90 managed 80.4%.
- Undersized hours: 2.4% with our upper estimate, about 10% for any
  forecast used alone.
- Say: "14 of the 15 undersized hours were in the first week of term. From
  day 8 the margin had widened and there was one in three weeks."
- The cost: the margin then stayed wide, and 48% of hours were oversized.

**6. Where it fails (3:20–4:10)**
- Missing meter data: without fallbacks a 6-hour gap removes 180 of 740
  hourly forecasts; with them every hour is planned.
- Worst days: two unusually quiet days (over-forecast) and August 20, a
  sudden 268 kW peak nothing announced.
- Error is 22 to 30% during the morning switch-on, 6 to 9% at night.
- A single home (Household 3): 46% error. The method transfers; the
  accuracy does not.

**7. Recommendation (4:10–5:00)**
- ML is worth it here for the calibrated upper estimate and for holidays,
  not for a much better average.
- Do not use it as an automatic switch, in the first week after a change of
  term (September proved it), or when the banner is not green.
- Open items: real generator ratings, fuel curves, the school calendar.

## Likely questions and short answers

**Why no graph model?**
The sites share no meaningful relationship structure: one campus and one
home, over 100 km apart, with no electrical or behavioural link. The guidelines
prefer no graph over an unneeded one.

**Why Ridge and not XGBoost or a neural network?**
On 4.5 months of data XGBoost was 17.2% against Ridge 16.3%, better in
some months and far worse in June. Trees also cannot predict above the
largest value they were trained on, and September is above it. Ridge
extrapolates and every forecast can be explained exactly.

**Why September as the test month?**
It is the last month, so the test is strictly in the future of everything
used for training and tuning, and it is the hardest month: term starts and
load is above anything seen before. It was fixed before modelling and
opened once.

**Why is the weather not used?**
We tested day-ahead forecast weather: 16.7% against 16.3% without it. Hot
days were forecast better than mild days. The load follows the timetable,
not the temperature, in these months. We have no winter data.

**How do you know there is no leakage?**
Features use only readings that finished before midnight. We check it two
ways on every day: the timestamp of each input, and by deleting all data
from midnight onward and confirming the features do not change.

**What does "90%" mean? Is it a guarantee?**
No. It is an empirical figure: about 9 hourly averages in 10 fell below the
estimate. It says nothing about peaks inside an hour, and it is weakest in
the first days after the load level changes.

**Why forecast net load directly instead of load minus PV?**
The generators supply load minus PV; generator output plus PV matches load
within 10% in 98% of readings. PV here follows the load more than the sun,
so no ML model beat the simple baseline for PV, and the
P90 of a difference is not the difference of two P90s.

**Is 0.5% undersized acceptable?**
That is the school's decision, not ours. The operator currently accepts 0%
and pays for it with 65% oversized hours. The reserve margin is the knob,
and "undersized" is measured against observed maxima, which are below the
real ratings.

**How much diesel does it save?**
We cannot say. We measure unused capacity, not litres; converting it needs
each unit's fuel curve, which we do not have.

**What happens when data is missing?**
The service falls back to last week's reading, then to the weekday
average, each with its own margin, and the page shows an amber banner
saying which hours are affected.

**Does it generalise?**
The method does: at Household 3 the same pipeline, with no retuning, beat
both baselines and kept 92% coverage. The accuracy does not: one home is
far less predictable than a campus, and there XGBoost beat Ridge.

**What would you do with more time?**
Get the real ratings and fuel curves, a full year of data, the academic
calendar, and test whether a short intraday update (re-forecasting at
06:00) catches days like August 20.

## Rehearsal plan

- Two run-throughs with a timer; cut words, not slides.
- In Q&A, each person answers questions on another person's stream.
- Assign who presents slides 1–2, 3–5 and 6–7 (Omar, Houssein, Sami).

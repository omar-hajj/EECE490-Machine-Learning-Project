# Model checked against chapter 6 (tuning and testing), and tuned

November 16, 2026. This applies the course notes "Statistical Model Tuning
and Testing" to the Azm model: first score it with the chapter's metrics,
then tune it the way the chapter prescribes.

**Order of events, stated plainly.** The September test was run once on
November 15 (`FINAL_RESULTS.md`) on the model as it then was. The tuning
below was done afterwards, on pre-September folds only. The chapter's rule
is "report final performance only once on the untouched test set", so:

- the official result remains `FINAL_RESULTS.md`;
- the tuned model's September numbers in section 3 are **post-hoc** and are
  not a test result;
- the tuning procedure was then given one **clean test** on a month nothing
  had read, Household 3's July 2025 (section 4);
- **the served model has not been changed.** Adopting the tuned model is a
  decision for the team (section 5).

## 1. Is the current model good, by the chapter's metrics?

Source: `scripts/score_course_metrics.py` → `outputs/course_metrics/`.
MBE = mean(actual − forecast), so a positive MBE means under-prediction.

### Regression metrics and the train/test gap

| Split | Model | MBE | MAE | RMSE | MAE / mean load |
| --- | --- | ---: | ---: | ---: | ---: |
| Training fit (in-sample) | Ridge (served) | 0.0 | 12.0 kW | 21.4 kW | 13.5% |
| Training fit (in-sample) | XGBoost | 0.0 | 10.6 kW | 18.0 kW | 12.0% |
| May–July, rolling origin | Ridge (served) | +2.0 | 15.0 kW | 26.2 kW | 16.5% |
| May–July, rolling origin | XGBoost | +1.4 | 16.2 kW | 32.9 kW | 17.8% |
| May–July, rolling origin | Same hour last week | −0.5 | 18.0 kW | 36.1 kW | 19.8% |
| August (validation) | Ridge (served) | +0.2 | 13.6 kW | 22.4 kW | 15.7% |
| August (validation) | XGBoost | +1.4 | 13.3 kW | 22.6 kW | 15.3% |
| August (validation) | Same hour last week | +3.7 | 15.0 kW | 26.9 kW | 17.3% |
| September (test) | Ridge (served) | +9.4 | 28.8 kW | 50.1 kW | 20.2% |
| September (test) | XGBoost | +11.4 | 30.1 kW | 51.7 kW | 21.0% |
| September (test) | Same hour last week | +10.5 | 32.1 kW | 54.7 kW | 22.4% |

- **Not overfitting.** Ridge's training error (12.0 kW) is close to its
  validation error (13.6 to 15.0 kW). XGBoost shows the larger gap
  (10.6 kW in training, 16.2 kW out of sample): more variance, as the
  chapter predicts for the more flexible model.
- **Some underfitting (bias).** Even in training the model is 13.5% off.
  Its inputs cannot explain more than that, so better features should help
  more than a more flexible algorithm. Section 2 confirms it.
- **The test error is about twice the validation error** (28.8 against
  13.6 kW). Relative to the load it is 20.2% against 15.7%: September's
  load is 60% higher, so the kW figure overstates the deterioration. This
  is distribution shift, not overfitting. A good test set should "reflect
  the same distribution we expect at deployment"; September does not
  resemble the training months, and it is the month that matters.
- **Biased low in September**: MBE +9.4 kW, the unsafe direction.

### Consistency across folds

| Month | Served MAE | XGBoost MAE | Last-week MAE |
| --- | ---: | ---: | ---: |
| May | 14.3 | 12.6 | 15.6 |
| June | 20.7 | 27.7 | 29.6 |
| July | 10.3 | 8.3 | 9.0 |
| August | 13.6 | 13.3 | 15.0 |
| September (test) | 28.8 | 30.1 | 32.1 |

The chapter: "if the fold scores vary a lot, the model may be unstable or
the dataset may be too small." They vary a lot (10 to 29 kW). The cause
here is the data: 4.5 months in which the load level changes twice. Ridge
is the steadiest of the three; XGBoost swings most (8 to 28 kW).

### Is the improvement real? (statistical tests)

Z-test on the hourly difference in absolute error, served Ridge minus the
other method:

| Split | Against | Mean difference | z | p |
| --- | --- | ---: | ---: | ---: |
| May–July | Same hour last week | −3.0 kW | −4.76 | <0.001 |
| May–July | XGBoost | −1.2 kW | −2.36 | 0.018 |
| August | Same hour last week | −1.4 kW | −2.36 | 0.018 |
| August | XGBoost | +0.3 kW | +0.86 | 0.39 |
| September | Same hour last week | −3.3 kW | −2.54 | 0.011 |
| September | XGBoost | −1.3 kW | −1.49 | 0.14 |

- **Against the baseline: significant in every split** (p < 0.05).
- **Against XGBoost: not significant** in August or September. We cannot
  claim Ridge is more accurate than XGBoost; we can only say XGBoost is not
  better, which is enough to keep the simpler model.
- Hourly errors are correlated in time, so these p-values are optimistic.
  The effect is also small (1 to 3 kW): significant is not the same as
  large.

### The decision as a classification problem

Each hour, the "class" is the generator configuration needed. The served
rule (upper estimate + 10% reserve) is compared with using a forecast
directly. September, 617 hours:

| Rule | Accuracy (right unit) | Picked too small | Picked too large | Macro F1 |
| --- | ---: | ---: | ---: | ---: |
| **Served rule** | **49.8%** | **2.4%** | 47.8% | 0.29 |
| XGBoost P90 rule | 67.7% | 7.0% | 25.3% | 0.33 |
| Last week's value alone | 81.8% | 9.4% | 8.8% | 0.43 |
| Ridge forecast alone | 81.8% | 9.7% | 8.4% | 0.46 |

Before September the served rule's accuracy was 77% (May–July) and 84%
(August), against 92% and 95% for the Ridge forecast alone.

- **By accuracy and F1 the served rule is the worst of the four.** It picks
  the right unit half the time in September.
- **By the costly error it is the best**: 2.4% of hours too small, against
  about 10% for a forecast alone. McNemar's test on "not undersized",
  served rule against Ridge alone: B = 45 hours only the served rule got
  safe, C = 0, chi² = 45, p < 0.0001. Against the XGBoost P90 rule: B = 29,
  C = 1, chi² = 26.1, p < 0.0001.
- This is the chapter's point about choosing the metric by the cost of
  errors: when a miss is expensive (an overloaded generator), recall on the
  dangerous cases matters more than accuracy. The rule deliberately trades
  accuracy for safety, and in September it traded too much: 48% of hours
  oversized.
- Per-class recall in September is weak for the mid-size units (G2 38%,
  G4 19%, G1 19%): when a mid-size unit was needed, the rule usually picked
  a larger one.

### Verdict

- **Forecast accuracy: acceptable, not good.** No overfitting, a real and
  significant gain over the baseline, but a 20% error in the month that
  matters and unstable from month to month.
- **Decision quality: safe but wasteful.** Right unit 50% of the time in
  September.
- **One clear methodological gap:** the Ridge regularization strength was
  never tuned. It was fixed at 1, which is almost no regularization. The
  chapter's workflow (try settings, compare on validation, then test once)
  had been skipped for the model's main hyperparameter.

## 2. Tuning

Source: `scripts/tune_model.py` → `outputs/tuning/`. All selection uses the
daily rolling-origin forecasts on four pre-September folds (May, June, July,
August), 2,670 common hours, 77 candidates. September is not used.

### What was tried, following the chapter

| Lever (chapter section) | Tried |
| --- | --- |
| Hyperparameter: regularization strength | Ridge alpha from 0.1 to 10,000 |
| L1 instead of L2 | Lasso, alpha from 0.2 to 8 |
| Feature engineering | load 48 h ago; yesterday's mean and maximum; mean of the same hour over 7 days; **same hour on the last similar day** (Monday looks at Friday, not Sunday) |
| Algorithm choice | XGBoost |
| Ensemble (averaging) | average of the best linear model and XGBoost |
| Decision threshold | quantile, look-back window and reserve of the sizing rule |

### Result for the point forecast

| Model | May | June | July | August | Mean fold MAE |
| --- | ---: | ---: | ---: | ---: | ---: |
| Current: Ridge, alpha 1 | 14.3 | 20.8 | 10.2 | 13.6 | 14.73 kW |
| Ridge, alpha tuned (1,000), same features | | | | | 13.40 kW |
| Ridge, alpha 1,000, + similar day + 7-day mean | | | | | 12.51 kW |
| **Lasso, alpha 2, + similar day + 7-day mean** | **10.3** | **19.1** | **6.8** | **11.6** | **11.96 kW** |
| Average of that and XGBoost | 10.8 | 21.4 | 7.0 | 12.1 | 12.81 kW |
| XGBoost alone | 12.6 | 27.7 | 8.4 | 13.3 | 15.47 kW |

- **Validation error falls by 19%** (14.73 to 11.96 kW), and it falls in
  every fold.
- **Tuning alpha alone gives 9%.** The curve has the shape the chapter
  describes: too little regularization (alpha 0.1 to 10: 14.7 kW), a best
  value (1,000: 13.4 kW), then underfitting (10,000: 16.6 kW).
- **The "similar day" feature is the best single addition.** The old model
  used "same hour yesterday", which on a Monday is a Sunday.
- **Lasso beats Ridge here**, and it selects features as the chapter says:
  of 173 inputs it keeps 7. The tuned model is

  forecast ≈ 0.59 × (same hour, last similar day) + 0.20 × (same hour last
  week) + 0.03 × (7-day mean of that hour) + 4 hour-of-week corrections.

  It dropped "same hour yesterday" and 164 of the 168 hour-of-week levels.
  The tuned model is simpler than the one it replaces.
- **The ensemble does not help** (12.81 kW): averaging in XGBoost adds its
  June error. More capacity is not what this problem needs.
- Fold spread did not improve (10.6 to 12.3 kW): June is still the hard
  month. Tuning lowered the error; it did not make the model more stable.

### Result for the sizing rule

Changing the quantile, window and reserve moves along a trade-off, like a
threshold on a ROC curve. For the tuned model, on 2,020 validation hours
(a selection of the efficient settings):

| Quantile | Window | Reserve | Coverage | Too small | Too large |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.95 | 21 days | 10% | 94.9% | 9 | 642 |
| 0.90 | 14 days | 5% | 92.9% | 12 | 444 |
| **0.90** | **28 days** | **10%** | **91.7%** | **13** | **382** |
| 0.90 | 21 days | 10% | 90.4% | 14 | 314 |
| 0.90 | 28 days | 0% | 91.7% | 16 | 269 |
| 0.85 | 21 days | 10% | 85.6% | 17 | 205 |
| 0.80 | 28 days | 10% | 81.8% | 20 | 167 |
| 0.80 | 21 days | 0% | 81.5% | 29 | 94 |

- The current setting (bold) is on the efficient frontier: no setting is
  both safer and less wasteful.
- **No setting was adopted.** The rule "fewest oversized hours among
  settings at least as safe as today's" returns the current setting. The
  differences near it are 1 to 3 hours out of 2,020, too few to choose on.
- Moving down the table is a policy choice, not a tuning result: for
  example quantile 0.85 would roughly halve oversizing (382 to 205 hours)
  for 4 more undersized hours (13 to 17). That is the school's decision.

## 3. Post-hoc check on September (not a test result)

`scripts/tune_model.py --rescore-test <zip>` scores both models on the same
607 September hours. September had already been opened, and the ideas tried
above were partly suggested by what failed in it, so this is an indication
only.

| September, 607 hours | Current model | Tuned model |
| --- | ---: | ---: |
| MAE | 28.8 kW | 26.4 kW |
| RMSE | 50.2 kW | 44.6 kW |
| MBE (under-prediction) | +9.8 kW | +6.3 kW |
| MAE / mean load | 20.0% | 18.4% |
| Coverage of the upper estimate | 88.6% | 89.3% |
| Hours picked too small | 15 | 12 |
| Hours picked too large | 292 | 294 |

- The gain carries over but shrinks: **8% lower MAE in September against
  19% on validation.** That is normal: settings chosen on validation look
  better there than anywhere else.
- Fewer undersized hours (15 to 12) and less bias.
- **Oversizing is unchanged** (48%). Tuning the forecast does not fix it;
  it comes from the margin staying wide after the first week, and from the
  policy choice above.

## 4. Clean test of the tuning procedure: Household 3, July 2025

Run once on November 16, 2026 with `scripts/transfer_test.py
--open-test-set`; record in `results/final_test_household_3.json`. The
script refuses to run again. July 2025 had never been read by any script:
the earlier runs skipped that workbook, and the rehearsal on June confirmed
it stayed unopened.

**What was fixed before July was read:** the candidate grid, the selection
rule (lowest mean MAE over monthly rolling-origin folds), and the
comparison (untuned Ridge with alpha 1, the selected setting, and "same
hour last week", on the same hours). Lasso strength is scaled to the
target's spread because Household 3 is in watts.

**Selection, on August 2024 to June 2025 only** (9 folds, 77 candidates):
Lasso with all five engineered features, validation MAE 158 W against 187 W
untuned (15% lower).

**Test, July 2025** (744 hours, mean load 816 W):

| Method | MBE | MAE | RMSE | MAE / mean load | Upper-estimate coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Same hour last week | +61 W | 549 W | 769 W | 67.4% | |
| Untuned (Ridge, alpha 1) | +149 W | 437 W | 593 W | 53.5% | 89.1% |
| **Tuned by the procedure** | **+44 W** | **403 W** | **525 W** | **49.4%** | **91.1%** |

- **The tuning holds up on unseen data.** MAE is 8% lower than untuned
  (403 against 437 W), RMSE 11% lower, and the under-prediction bias falls
  from 149 W to 44 W. Paired Z-test on hourly absolute errors: mean
  difference −34 W, z = −4.0, p < 0.001 (optimistic, since hourly errors
  are correlated).
- **About half the validation gain survives the test**: 15% on validation,
  8% on the test month. Azm showed the same pattern (19% on validation, 8%
  on September post-hoc). The validation figure overstates the benefit, as
  the chapter warns; the test figure is the one to quote.
- The upper estimate stays calibrated: 91.1% coverage against a 90% target.
- **What this does and does not show.** It shows the tuning procedure
  (regularization strength plus the engineered features, selected on
  folds) gives a real, modest improvement at a second site. It does not
  measure the tuned model at Azm, and a single home is still forecast
  poorly in absolute terms (49% error).

## 5. What to do with this

- **For the report and presentation:** the evaluation in section 1 and the
  tuning study in section 2 are both valid as they stand. Present
  `FINAL_RESULTS.md` as the Azm test result, and the tuning as "what we
  would ship next: validated on four folds at Azm and confirmed by a clean
  test at Household 3 (8% lower error)".
- **Adopting the tuned model in the API** is possible but has a cost: the
  served model would then differ from the one the final test measured, and
  there is no unopened month left to test it on. If the team wants it
  served, the Backtest page, Failure gallery and Why panel must be rebuilt
  on the tuned model's forecasts so the page stays consistent.
- **Not tunable from here:** the month-to-month instability and the
  first-week failure. Those need more data (a full year) or information the
  model does not have (the academic calendar).

## Reproduce

```powershell
.\.venv\Scripts\python.exe scripts/score_course_metrics.py
.\.venv\Scripts\python.exe scripts/tune_model.py
.\.venv\Scripts\python.exe scripts/tune_model.py --rescore-test '..\Data for EECE 490 Project.zip'
.\.venv\Scripts\python.exe scripts/transfer_test.py --archive '..\Data for EECE 490 Project.zip'
```

The first three take about a minute each. The last is the rehearsal on June
(about 5 minutes); the July test itself has been run and must not be rerun.

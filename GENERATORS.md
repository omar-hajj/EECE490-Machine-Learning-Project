# Azm generators: observed capacities, draft rule, wrong-generator hours

Updated November 10, 2026. Roadmap Week 1 items: "Extract each generator's
rated or observed maximum output from the data and draft the selection rule"
(C) and "Define a use-linked metric" (B). Only rows before September 1, 2026
were read; September stays reserved for the final test.

## What the data show

Source: the Azm export's four `Generator N Power` / `Generator N Status`
columns, 39,491 five-minute rows from April 16 to August 31, 2026.

| Unit | Highest observed output | Typical output while running | Share of time running |
| --- | ---: | ---: | ---: |
| G3 | 146.1 kW | 73 kW | 38.3% |
| G2 | 236.8 kW | 79 kW | 4.0% |
| G4 | 315.0 kW | 85 kW | 35.2% |
| G1 | 413.4 kW | 95 kW | 24.0% |

- Generator output plus PV equals campus load within 10% in 98% of rows, and
  utility power was never on. So **net load (load − PV) is what the
  generators must supply**, which supports the API's `signed_net_kw`.
- A generator ran in every sampled row; the school never ran with all units off.
- The roadmap quoted peaks of about 160, 315, 415 and 415 kW. Through August we
  see 146, 237, 315 and 413 kW. The difference (mainly G2) is probably in
  September, which we did not open.

### Current practice (inferred from the status columns)

The school could not yet tell us how units are chosen, so per the roadmap's
fallback we describe the observed pattern. Counting only whole hours where a
single configuration ran unchanged (3,053 of 3,294 hours):

| Configuration | Whole hours | Median net load | 95th percentile |
| --- | ---: | ---: | ---: |
| G3 alone | 1,147 | 74 kW | 89 kW |
| G4 alone | 1,057 | 83 kW | 171 kW |
| G1 alone | 719 | 97 kW | 144 kW |
| G2 alone | 120 | 78 kW | 117 kW |
| G1 + G4 | 6 | 370 kW | 402 kW |
| G2 + G3 + G4 | 3 | 273 kW | 317 kW |

The operator often runs G4 or G1 (315–413 kW) at loads G3 (146 kW) could
carry, which is the "wasted diesel" the project targets. Parallel running is
rare and happens only at high load. This should still be confirmed with the
school.

## Draft selection rule (`config/azm_generators.json`)

> Run the smallest allowed configuration whose capacity covers the forecast
> net load × (1 + reserve margin). Ties go to the operator.

- **Capacity** is the highest observed 5-minute output. That is a lower bound
  on the real rating, so the rule errs toward larger units.
- **Allowed configurations** are every single unit, plus any parallel
  combination that ran unchanged for at least 3 whole hours: G1+G4 (728 kW)
  and G2+G3+G4 (698 kW). Brief overlaps during handover do not count.
- **Reserve margin** is a placeholder 10%; the team and school must set it.
- Status: `draft_from_observed_data_pending_school_confirmation`. Rerun with
  `scripts/extract_generators.py` if the data or thresholds change.

## Use-linked metric: wrong-generator hours

For each hour, the forecast picks a configuration using the rule above. The
**needed** configuration is the smallest that covers the actual net load,
with no margin. The pick is:

- **undersized**, or overload risk, when its capacity is below the actual net load;
- **oversized**, or wasted fuel, when it is larger than the needed configuration;
- **right-sized** otherwise.

August validation, 734 hours shared by every method, margin 10%:

| Method | Undersized (overload risk) | Oversized (wasted fuel) | Right-sized | Shortfall kWh | Excess capacity kWh |
| --- | ---: | ---: | ---: | ---: | ---: |
| Yesterday baseline | 12 (1.6%) | 23 (3.1%) | 699 (95.2%) | 402 | 2,321 |
| Last-week baseline | 13 (1.8%) | 17 (2.3%) | 704 (95.9%) | 496 | 1,777 |
| Weekday-profile baseline | 6 (0.8%) | 64 (8.7%) | 664 (90.5%) | 384 | 5,805 |
| Ridge point forecast | 9 (1.2%) | 20 (2.7%) | 705 (96.0%) | 464 | 1,814 |
| XGBoost point forecast | 12 (1.6%) | 30 (4.1%) | 692 (94.3%) | 545 | 2,721 |
| XGBoost direct P90 net | 6 (0.8%) | 56 (7.6%) | 672 (91.6%) | 346 | 5,725 |
| Weekday P90 baseline | 4 (0.5%) | 131 (17.8%) | 599 (81.6%) | 361 | 17,589 |

### How to read this

- **August is an easy month for this metric.** Actual net load needed only
  G3 in 722 of its 740 hours (maximum 268 kW). So nearly every method is
  "right" most of the time, and the differences come from a few dozen
  high-load hours. September load is much higher (the roadmap notes weekday
  mornings around 500 kW), so the final test will separate methods far more.
- The trade-off appears as expected: P90 methods halve overload hours compared
  with point forecasts but oversize three times as often. Ridge has the best
  balance among point forecasts here, consistent with its MAE result.
- These are validation numbers under a draft policy, not final results.

## Next steps

1. Score the same metric on the May–July backtests, where load is higher, to
   get a less one-sided comparison before the September test.
2. Week 2 (C): serve the recommendation in `/forecast` (P90 net × margin) and
   show it in the Tomorrow view's colour-coded generator strip.
3. Confirm the ratings, allowed combinations and margin with the school. Then
   replace the observed maxima and flip the policy status.

Reproduce:

```powershell
python scripts/extract_generators.py --archive 'Data for EECE 490 Project (1).zip'
python scripts/score_generator_choice.py
```

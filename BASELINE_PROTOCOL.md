# Approved first baseline experiment

Status: approved by the user on November 8, 2026, after a plain-language
explanation. The implemented sampling rule follows that explanation: skip
incomplete hours. The earlier draft's allowance of 10 of 12 Azm readings was
replaced with the complete-hour requirement before the run.

The purpose is to establish history-based demand and solar baselines while
the other sites' village location and meter metadata remain unavailable.
This experiment does not evaluate location-only mode and cannot approve it.

## Approved data rules

1. Preserve original files. Read timestamps as recorded local clock times;
   resolve slash-date order using the month in each filename. Do not shift
   timezones or join weather until the clock conventions are confirmed.
2. Work in each source's original numeric power units. Report normalized
   errors for comparisons. Azm's demand and solar PV units were subsequently
   confirmed by the user as kW; no numeric conversion is needed. Other sites'
   units remain unverified. Do not infer equipment ratings.
3. Form hourly means separately for each recorded demand/production channel.
   For Azm, retain an hour only with all 12 usable five-minute readings.
   For the half-hourly sources, require both distinct half-hour readings.
   Require exactly one reading in each nominal sampling slot, so repeated
   samples cannot conceal a missing interval.
   Do not fill missing values or bridge missing hours. Validate cadence before
   treating these as the expected sampling intervals.
4. Keep recorded nonnegative values, including zeros, for this exploratory
   run. Reject non-finite or negative demand/PV values. Do not automatically
   remove spikes or frozen readings, invent solar capacities, subtract PV,
   or infer battery behavior. Label scores provisional until source semantics
   and sensor problems are resolved.
5. Score every site separately. Explicitly flag the duplicated Household 1/2
   months. Do not present a pooled multi-site score as independent evidence
   or train a transferred model on these duplicated periods.

## Approved chronological periods

| Site group | Training | Validation | Reserved final test, not scored now |
| --- | --- | --- | --- |
| Azm University | Available data April 16-July 31, 2026 | August 2026 | September 2026 |
| Other seven sites | Available history through May 31, 2025 | June 2025 | July 2025 |

Absent months remain absent. The household/municipality histories extend
back to August 2024; the industrial sources begin in January 2025.

## Baselines and evaluation

- Predict the same hour yesterday with an exact timestamp lookup.
- Predict the same hour last week with an exact timestamp lookup.
- Predict the mean training-period value for that weekday and hour.

Forecasts are issued once at midnight for the following 24 hourly buckets.
The weekday profile is fitted to training data only. Yesterday/week-ago
lookups must precede the issue time; later validation days may use earlier
validation measurements that would already be available in operation.

Report MAE, RMSE, maximum absolute error, nMAE, and prediction coverage for
each site and target. Compare the three baselines on identical observed
validation hours, and separately report how many eligible hours each could
predict. Do not silently drop missing predictions or score the final test.

The experiment supplies initial history-based reference scores. A true
location-only comparison still requires the village's location, consistent
units and a separately agreed unseen-site evaluation design. Equipment
recommendations additionally require supplied capacities and policy inputs.

After the first run, the user confirmed that Azm `Production` is solar PV,
`Load Power` is campus load, and both are in kW. Its target label is now `pv`;
the original source column name remains recorded. This metadata correction
does not change the aggregation rules, predictions, errors, or reserved test.

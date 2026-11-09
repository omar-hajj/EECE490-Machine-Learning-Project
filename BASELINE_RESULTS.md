# First baseline results

The approved first check is complete. Three simple history-based forecasting
methods were evaluated separately for eight sites, using August 2026 for Azm
and June 2025 for the other sites. The reserved September/July test months
were not scored.

These are provisional measurements of the supplied recorded channels.
No advanced ML model, location-only model, or generator operating policy has
been validated by this experiment.

## Electricity demand

All three methods use the same observed validation hours within each site.
Lower error is better. nMAE is average absolute error divided by average
actual demand; it is not a percentage accuracy score or MAPE.

| Site | Yesterday's pattern | Last week's pattern | Average weekday pattern | Lowest measured error |
| --- | ---: | ---: | ---: | --- |
| Azm University | 28.2% | 17.3% | 16.6% | Average weekday |
| Household 1 | 9.0% | 8.0% | 30.8% | Last week |
| Household 2 | 8.9% | 9.3% | 51.5% | Yesterday |
| Household 3 | 55.2% | 53.6% | 50.7% | Average weekday |
| Industrial 1 | 20.7% | 19.6% | 16.3% | Average weekday |
| Industrial 2 | 123.9% | 116.5% | 86.2% | Average weekday |
| Industrial 3 | 116.2% | 112.7% | 82.2% | Average weekday |
| Municipality | 103.9% | 131.7% | 102.6% | Average weekday |

For example, Household 1's last-week baseline has an average absolute error
of about 23.94 source units, against average actual demand of about 300.66
source units: 23.94 / 300.66 is approximately 8.0%.

An error above 100% is possible: the average mistake can exceed the site's
average recorded demand. It is not a negative accuracy score. We have not
established whether the large errors arise from genuine variation, sensor
issues, changing recording conventions, or limitations of these methods.

No single baseline has the lowest error at every site. These validation
results provide reference values for later ML comparisons; they do not
select a final production model.

## Solar and production channels

For recorded PV, the lowest measured nMAE among the three methods is 25.9%
for Household 1, 20.1% for Household 2, 46.9% for Household 3, 24.5% for
Industrial 1, 32.5% for Industrial 2, 47.4% for Industrial 3, and 83.1% for
Municipality. These are full-day scores, including recorded nighttime values;
no sunlight-based masking was applied.

The user confirmed that Azm's `Production` column is solar PV and that both
`Production` and `Load Power` (campus load) are measured in kW. Azm's lowest
solar PV nMAE is 36.9%, using the average weekday pattern. This clarification
changes channel labels and unit metadata, not the numerical forecasts or
errors. The results remain provisional and the final test is still reserved.

## Coverage and verification

- Azm's comparison uses 734 of August's 744 calendar hours. Four hours lack
  complete usable actual readings; six additional hours lack history needed
  by at least one baseline.
- Every other site's comparison uses all 720 June hours for each channel.
- The preparation retained 83,488 hourly channel observations across training
  and validation, counting load and PV/production separately.
- The baseline run opened 54 measurement workbooks and did not open the seven
  reserved July workbooks. The Azm export's September rows were excluded
  before their values entered hourly preparation or scoring.
- SHA-256 checks before and after the run confirmed the source ZIP was
  unchanged.
- All 30 code tests passed. An independent checker reconstructed saved
  predictions and reconciled errors, coverage and issue times for all 16
  site/channel groups.

## Interpretation limits and next steps

Azm campus-load and solar-PV units are confirmed as kW. Its campus load includes
solar-served demand and its meter clock follows Lebanese local time with DST.
Village units were subsequently confirmed as W. Six source clocks matched
the reported DST transition; Municipality's clock remains under review.
The other sites' meter boundaries relative to solar remain unverified.
Zeros, spikes and frozen values were retained under the approved first-check
rules. Household 1 and Household 2 share duplicated February/March data, so
their results are not independent evidence of transfer across sites.

The village was subsequently identified as Deir Qanoun en Nahr. A separate
approved six-site location-only comparison is now documented in
`LOCATION_ONLY_RESULTS.md`; no acceptance cutoff was chosen automatically.

Before interpreting the difficult sites or selecting ML models, confirm the
source column meanings and examine their validation-period failures.
Generator recommendations for real equipment also require verified usable
capacities, permitted combinations, and a reserve margin.

## Reproducing the run

The approved rules are in `BASELINE_PROTOCOL.md` and `config/baseline.json`.
With the project dependencies available:

```powershell
python scripts/run_baselines.py --archive 'Data for EECE 490 Project (1).zip' --config config/baseline.json --sites config/sites.json --output-dir outputs/baselines_confirmed_azm
python scripts/verify_baseline_outputs.py --output-dir outputs/baselines_confirmed_azm --archive 'Data for EECE 490 Project (1).zip'
```

Current generated evidence is in `outputs/baselines_confirmed_azm/results.json`,
`hourly_data.csv`, `validation_predictions.csv`, and `summary.md`.
The JSON records source/configuration/code hashes, scores and coverage.
Generated observations and predictions remain ignored by Git.
The original run under `outputs/baselines/` is retained as the pre-confirmation
snapshot; the metadata update does not change any numerical scores.

# Site electricity forecasting for Lebanon

## Confirmed scope

Forecast the next 24 hours of electricity demand and solar production for
individual sites in Lebanon. Provide generator capacity recommendations when
the site's equipment and permitted operating configurations are known.

Compare two input modes:

- History-based: past site electricity measurements, location, and equipment.
- Experimental location-only: location and information derived from location
  and the forecast date. No target-site historical load, PV, consumption scale,
  equipment capacity, building type, or site identifier as a predictive feature.

The location-only forecasting experiment can still use other sites for
training. It cannot train on the held-out site's rows or fit normalization from
that site's electricity readings. Its actual readings are used only for
scoring. Experiment records must establish this separation.

Location alone does not identify generator capacities or solar installation
size. Generator recommendations always need equipment information. The
location-only PV experiment must predict absolute production without knowing
the held-out installation size; a system that asks for solar capacity is a
different input mode and must be labeled accordingly.

The user will inspect the measured comparison before choosing an acceptable
error cutoff. No percentage threshold has been approved.

## Work sequence

1. Inventory and inspect the original files without overwriting them. Verify
   duplicate data, missing intervals, source definitions and units.
2. Confirm remaining coordinates and source clock/timezone. The user confirmed
   the historical export belongs to Azm University at the supplied Maps pin.
   All seven other sites are in Deir Qanoun en Nahr (دير قانون النهر).
   The user approved the representative village point for weather lookups;
   exact building coordinates remain unknown. Weather
   response coordinates may represent grid cells, so their differences alone
   do not prove a mismatch; download provenance remains unverified.
3. Agree on data cleaning and hourly aggregation rules. Preserve raw data and
   record every transformation. Resolve batteries and meter boundaries before
   deriving net load; do not assume load minus PV is valid for every meter.
4. Fix chronological training/validation/test periods for each source. The
   roadmap's April-July/August/September 2026 split applies only to compatible
   data. The other sites cover different years. Hold evaluation sites out of
   location-only training, including preprocessing. Keep duplicated periods
   together or exclude them under an agreed rule.
5. Implement yesterday, last-week and weekday-profile baselines. Every feature
   must exist at the midnight forecast issue time; lag lookups must not cross
   missing periods by row position.
6. Compare Ridge and XGBoost separately for demand and PV. Evaluate a model
   trained across sites for the location-only experiment. Use forecast weather
   available at issue time, not actual future weather. Treat supplied weather
   as unverified until its coordinates and forecast provenance are resolved.
7. Produce per-site/per-target paired MAE, RMSE, maximum absolute error and
   nMAE. Here nMAE = mean absolute error / mean actual; it is undefined for an
   all-zero target. Report site coverage and missing predictions. Show the
   user results before selecting the location-only acceptance limits. A
   comparison without verified held-out sites cannot establish transfer.
8. Implement uncertainty-aware net-load estimates and equipment-configured
   generator logic. Validate quantile coverage; P90 demand minus P90 PV is
   not generally P90 net demand. Supply usable capacities, permitted unit
   combinations and a reserve margin explicitly. Flag infeasible demand.
9. Connect trained models to the roadmap's FastAPI service and Streamlit
   application. Show missing inputs and fallback status. Add Docker, logged
   backtests and explanations once those outputs exist.
10. Freeze the experiment design, evaluate the final test sets once, document
    limitations, run a fresh installation check, and prepare the course
    poster/presentation and contribution record.

## Current implementation

- Repeatable ZIP/workbook inspection: `scripts/audit_data.py`.
- Paired error calculations: `src/lebanon_energy/evaluation/metrics.py`.
- Prediction comparison command: `scripts/compare_modes.py`.
- Explicit generator capacity/configuration logic:
  `src/lebanon_energy/generators/policy.py`.
- Configuration files keep unknown coordinates, units and policy inputs null.
- Approved complete-hour preparation and three historical baselines:
  `src/lebanon_energy/data/preparation.py`, `src/lebanon_energy/models/baselines.py` and `scripts/run_baselines.py`.
- Independent saved-output reconciliation: `scripts/verify_baseline_outputs.py`.

The approved hourly dataset, Ridge/XGBoost point forecasts and a first direct
net-load P90 experiment now exist; see `MODEL_RESULTS.md`. Preliminary weather
comparisons were explicitly approved. Saved models and paired predictions
were independently replayed. The source remains unchanged and final test
months are unscored. A first six-site location-only comparison is now complete;
see `LOCATION_ONLY_RESULTS.md`. May–July Azm checks and July split calibration
are complete; see `AZM_BACKTEST_RESULTS.md`. A local FastAPI demo serves Azm
demand and PV with explicit fallbacks. No visual interface or Docker deployment
exists yet. The local Python/VS Code environment is ready.

## Decisions and information still needed

- The Azm Maps pin and the other sites' village (Deir Qanoun en Nahr) are
  confirmed. Village-point weather lookup is approved and 6,600 UTC forecast
  hours are cached. Units were confirmed as W and six clocks matched the raw
  DST inspection. The user approved April-May fitting/selection and June
  held-out-site evaluation, with Households 1/2 held out together. The measured
  location-only errors exceeded history-based errors in all 12 comparisons.
  This is within-village evidence, not nationwide geographic validation.
- Azm's campus load includes solar-served demand; PV/load kW units and the
  Lebanese local meter clock with DST are confirmed. All village units are
  confirmed as W. Municipality's clock differs from the other six during the
  March inspection and remains pending; other sites' meter boundaries relative
  to PV still need confirmation. Weather publication timing remains unverified.
- Parallel operation is confirmed possible at Azm. Actual generator usable
  capacities are explicitly unknown. Permitted combinations and reserve
  margin remain unresolved; no equipment recommendations have been made.
- The direct net-load P90 achieved 85.3% validation coverage, not its intended
  90%. Earlier-month coverage varied widely. July split calibration reduced
  later coverage from 96.3% to 83.5%, so the adjustment is not served. Further
  uncertainty modeling is needed before operational recommendations.
- The user approved the first baseline protocol. Further cleaning changes
  still require evidence and agreement; the exploratory scores do not settle
  ambiguous units, meter meanings, or the source of large errors.

## Method references

- Original project roadmap: `EECE490_3-Week_Roadmap.docx`.
- [Scikit-learn: avoiding data leakage](https://scikit-learn.org/stable/common_pitfalls.html).
- [Scikit-learn: time series and grouped evaluation](https://scikit-learn.org/stable/modules/cross_validation.html).
- [Open-Meteo: grid-cell coordinates and fixed response UTC offsets](https://open-meteo.com/en/docs).
- [Open-Meteo: previous forecast runs](https://open-meteo.com/en/docs/previous-runs-api).

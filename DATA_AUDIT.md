# Initial data audit

Inspection date: November 8, 2026.

Source: `Data for EECE 490 Project (1).zip`, including its nested archives.
The source archive and workbooks were read in memory and were not modified or
extracted. No model or cleaning policy was selected during the initial audit.
Scope decisions supplied afterward are recorded below and in `config/project.json`.

## Confirmed project direction

The intended product serves individual sites across Lebanon. Azm School is a
candidate case study, not the geographic limit of the product. The available
sites must be evaluated before making claims about generalization.

## Measurement inventory

Counts below exclude headers and wholly empty rows. Periods describe the first
and last timestamps, not continuous coverage. Slash-formatted timestamps were
interpreted against the month in the source filename for inspection only; no
normalized dataset was written.

| Source group | Workbooks | Records | Earliest timestamp | Latest timestamp |
| --- | ---: | ---: | --- | --- |
| Historical export, confirmed Azm University source | 1 | 48,080 | 2026-04-16 18:08:49.438 | 2026-09-30 23:56:50.439 |
| Household 1 | 10 | 14,590 | 2024-08-01 00:00 | 2025-07-31 23:30 |
| Household 2 | 9 | 13,102 | 2024-08-01 00:00 | 2025-07-31 23:30 |
| Household 3 | 10 | 14,590 | 2024-08-01 00:00 | 2025-07-31 23:30 |
| Industrial 1 | 7 | 10,174 | 2025-01-01 00:00 | 2025-07-31 23:30 |
| Industrial 2 | 7 | 10,174 | 2025-01-01 00:00 | 2025-07-31 23:30 |
| Industrial 3 | 7 | 10,174 | 2025-01-01 00:00 | 2025-07-31 23:30 |
| Municipality | 10 | 14,590 | 2024-08-01 00:00 | 2025-07-31 23:30 |

The historical export contains `Time`, `Production`, `Load Power`, four
generator power columns, four generator status columns, `Utility Status`, and
`Utility Power`. Its column headers do not specify power units. Its first two
timestamps are five minutes apart. The user subsequently confirmed
`Production` as solar PV and `Load Power` as campus load, both in kW.
The user later confirmed that campus demand includes solar-served demand and
that the meter clock follows Lebanese local time including DST. The other
sites' units were later confirmed as W and their clocks reported as Lebanese
local time. Direct March inspection supports this for six sites but shows a
different Municipality gap. See `VILLAGE_CLOCK_INSPECTION.md`; no timestamp
correction was applied.

Household, industrial, and municipality files generally contain `Time`,
`Load power (w)`, `Grid power (w)`, `PV power (w)`, and `Battery power (w)`.
Industrial 3 May also contains `Battery state of charge (%)`. The sampled
readings are 30 minutes apart. Units must be checked against source definitions,
especially where numeric magnitudes differ substantially between sites.

## Confirmed data issues

- Household 1 and Household 2 February 2025 have identical complete data rows.
- Household 1 and Household 2 March 2025 have identical complete data rows.
  These pairs were identified by hashes of all cell values, excluding headers.
  They must not be counted as independent evidence in a transfer evaluation.
- Household 2 January 2025 has 56 blank measurement cells: 14 each in load,
  grid, PV and battery power. Their treatment is pending.
- Timestamps use Excel date cells, ISO strings, and both day/month and
  month/day slash formats. A blanket date parser would be ambiguous.
- Source periods differ. The roadmap's 2026 calendar split cannot be applied
  literally to the 2024-2025 datasets.
- Zero load readings occur in several sources. This inspection does not
  classify them as outages, missing readings, or genuine zero demand.
- All inspected measurement timestamps could be parsed using the filename
  month as a consistency check. This is not a full timezone or DST validation.

The audit has not yet established meter boundaries, battery sign conventions,
frozen readings, power balance, all missing intervals, or whether different
files contain duplicated individual channels. The industrial files were not
found to be identical complete workbooks by the data-row hash check; broader
duplication claims in the roadmap require further verification.

## Weather files already supplied

Both weather CSVs contain a metadata block, a blank line, a data header, and
4,032 hourly data records spanning April 16 through September 30, 2026.

| File | Latitude | Longitude | Weather columns |
| --- | ---: | ---: | --- |
| `azm_weather_forecast_day1.csv.csv` | 34.45713 | 35.867466 | Temperature, humidity, shortwave radiation, cloud cover, diffuse radiation, direct radiation; columns labeled `previous_day1` |
| `azm_weather_observed.csv.csv` | 34.411247 | 35.88679 | Temperature, humidity, shortwave radiation, cloud cover, diffuse radiation, direct radiation |

Their coordinates differ. Open-Meteo's documentation explains that returned
coordinates may identify weather grid-cell centers several kilometres from
the requested point; the difference alone does not establish a data error.
See [the response documentation](https://open-meteo.com/en/docs).
Both metadata blocks report `Asia/Beirut`, an offset
of 7,200 seconds, and `GMT+2`. The correct site coordinates, timestamp handling,
forecast provenance, and availability at the forecast issue time require
validation before joining these files to meter data. A `previous_day1` column
name alone does not establish that all features were available at midnight.

## Other supplied material

The archive also contains a large Building Data Genome Project 2 archive,
regional/network documents and models, a 2018 weather workbook, and
`LebanonSystem.xlsx`. The latter includes generator parameters and monthly
hour-of-day demand profiles, not a dated site consumption time series.
Their role in the revised project has not been decided.

## Scope decisions supplied after the audit

The user requested both history-based and experimental location-only input
modes. Location-only mode is retained only if its measured error is acceptable;
the user will choose acceptance limits after seeing the measured comparison.
Demand forecasting, solar forecasting, and generator recommendations are all
in scope.

The user supplied a Google Maps link resolving to Azm University at
34.4453066, 35.8440889 and confirmed it is the site associated with the historical
export. The user also confirmed that all seven other sites are in the same
village in south Lebanon. On November 9, the user identified it as دير قانون
النهر (Deir Qanoun en Nahr) and approved the village map point (approximately
33.2993 N, 35.31123 E) for weather retrieval. The group and separate weather
coordinates are recorded in configuration; exact meter coordinates remain
unknown. Coordinate source: https://mapcarta.com/12896870.

Source units and definitions, site coordinates, and evaluation design still
need resolution before selecting cleaning rules or training models.

The user approved the first history-based check after a plain-language
explanation. `BASELINE_PROTOCOL.md` records the complete-hour rule used in
the run. The initial results are documented in `BASELINE_RESULTS.md`; the
original files remain unchanged and reserved test months were not scored.

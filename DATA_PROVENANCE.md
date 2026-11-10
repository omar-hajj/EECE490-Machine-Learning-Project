# Data provenance note

Roadmap Week 1, stream A: "source, period, units, known issues, every change
made, and which files are excluded and why". Written on November 10, 2026,
one data check at a time. Items still waiting on the school are listed under
"Open items" at the end.

Final test months were never opened for these checks: September 2026 for
Azm, July 2025 for the village sites.

Every number in the checks below is reproduced by one command, which writes
`outputs/data_checks/results.json` and `summary.md`:

```powershell
python scripts/data_checks.py --archive 'Data for EECE 490 Project (1).zip'
```

## Source

- Archive: `Data for EECE 490 Project.zip` (named
  `Data for EECE 490 Project (1).zip` in older commands), SHA-256
  `f7de0f76ca533604134a4968be672c53c49116a37c860babd9bdb15c23b367aa`.
  The original archive is never modified. Every pipeline run checks its
  hash before and after reading it.

### Sites the project's results rely on

Decided by Omar on 2026-11-10, following the roadmap: Azm is the main site, and
Household 3 is the second site for checking that the method transfers. Why
the other sites are not used is explained under "Excluded files".

| | Azm | Household 3 |
|---|---|---|
| File | `2026-10-21 14_06_24Historical data.xlsx` (one workbook) | `Household3 Data.zip` (10 monthly workbooks) |
| What it is | University campus with four diesel generators and solar; confirmed by the user's map pin (34.4453066, 35.8440889) | Home with solar, battery and grid, in Deir Qanoun en Nahr; exact location unknown, village point 33.2993, 35.31123 used for weather |
| Period in the file | 2026-04-16 18:08 to 2026-09-30 23:56 | 2024-08-01 to 2025-07-31, with October and November 2024 missing |
| Training / validation / final test | Apr 16 – Jul 31 / Aug / Sep 2026 | to May 31 / Jun / Jul 2025 |
| Sampling | Every 5 minutes | Every 30 minutes |
| Columns used | `Load Power` = campus demand including what solar supplies; `Production` = solar PV; 4 × `Generator N Power` and `Generator N Status` | `Load power (w)`, `PV power (w)`; `Grid power (w)` and `Battery power (w)` for checks |
| Units | kW (confirmed by the user) | W (confirmed by the user) |
| Clock | Lebanese local time with summer time (confirmed) | Lebanese local time with summer time (confirmed; consistent at the March 2025 change) |
| Timestamp formats | ISO text | Excel dates |
| Rows read (before the test month) | 39,491 | 13,102 (July workbook not opened) |
| Complete hours kept | 3,262 | 6,541 (after the freeze in section 2) |

Row and hour counts come from `outputs/baselines_confirmed_azm/results.json`,
written by `scripts/run_baselines.py`.

## Checks and changes

### 1. Azm hourly load jumps above 200 kW: real, kept

**Question.** Are sudden rises in Azm's load real (the school opening) or meter
errors? (Roadmap: "Look at Azm's 42 hourly jumps above 200 kW".)

**Method.** Average the 5-minute readings into clock hours (April 16 to
August 31, 2026). A jump is a change of more than 200 kW from the previous
hour.

**Result: 12 jumps, all real.**

- All 12 are increases, at 6:00 or 7:00 AM, Monday to Thursday, 7 in June
  and 5 in July.
- In all 12, the separately metered generator output plus PV rose by the
  same amount as the load. A load-meter error would not have made the
  generators produce more, so the rises are real.
- No single 5-minute step exceeds 200 kW. The load ramps up over the hour,
  as equipment switches on.
- The morning jump moves from 6 AM to 7 AM from June 29. This could be a
  timetable change; to confirm with the school.

**The roadmap's count of 42 was not reproduced.** Ten ways of counting gave 0,
2, 12, 12, 25, 27, 28, 69, 82 and 113. None gives 42. The team treats the 42
as a counting mistake in the roadmap, possibly because it included
September.

**Change made:** none. All jumps stay in the data.

### 2. Household 3 frozen readings: one stretch masked

**Question.** Are readings stuck on one value for 3 hours or more?
(Roadmap: "41 rows stuck on one value for 3 hours or more".)

**Method.** Look for 6 or more consecutive half-hour readings with
identical non-zero values (August 2024 to June 2025). Long runs of exact
zeros are normal: there is no solar at night and no grid during outages.

**Result.**

| Stretch | What repeats | Verdict |
|---|---|---|
| 2025-04-04 19:30 to 2025-04-05 04:00 (18 readings, 9 h) | Load 137, grid 311, PV 0, battery 129: all four channels identical | Meter freeze |
| 2024-12-16 20:30 to 2024-12-17 01:30 (11 readings) | Battery -20 W only | Standby draw: kept |
| 2024-12-29 01:00 to 06:00 (11 readings) | Battery -20 W only | Standby draw: kept |

The December stretches are kept because the other channels keep changing,
and the neighbouring battery readings are -19 and -21 W. These three
stretches total 40 readings, close to the roadmap's 41.

**Change made** (decided by Omar, 2026-11-10): the April freeze readings are
treated as missing. The complete-hour rule then drops 10 hours, leaving
6,541 of 6,551 retained hours per target. Implementation: `frozen_readings`
in `config/baseline.json` and `mask_frozen_readings` in
`src/lebanon_energy/data/preparation.py`, recorded in `BASELINE_PROTOCOL.md`.
Household 3's June validation nMAE moved by less than 0.1 percentage point
for every method. No other site changed.

### 3. Household 3 power balance: consistent, nothing flagged

**Question.** Does energy in equal energy used? (Roadmap: "grid + PV − battery
vs. load ... agrees within 20% in about 70% of rows, so flag the rest".)

**Method.** For each half-hour reading, August 2024 to June 2025 with the
April freeze removed (13,084 readings):

> supplied = grid + PV − battery (battery positive = charging)

This sign convention is confirmed: with the opposite sign, only 2.2% of
readings agree within 20%.

**Result.**

- With the roadmap's rule, 67.8% of readings agree within 20%, which matches
  its "about 70%".
- The disagreement is systematic, not random. Supply exceeds load by a median
  of 46 W (middle 90% of readings: 18 to 88 W). Across all readings it
  follows **gap ≈ 38 W + 2.8% of load**. That is the shape of inverter losses:
  a fixed standby draw plus a small share of the power handled. The
  inverter-loss explanation is our interpretation; the installer has not
  confirmed it.
- The 20% rule fails mainly when load is small, because a fixed ~45 W is a
  large share of a small load:

| Month | Median load | Within 20% |
|---|---:|---:|
| Aug 2024 | 643 W | 99.9% |
| Sep 2024 | 445 W | 98.7% |
| Dec 2024 | 328 W | 77.3% |
| Jan 2025 | 313 W | 79.0% |
| Feb 2025 | 216 W | 58.0% |
| Mar 2025 | 288 W | 70.5% |
| Apr 2025 | 202 W | 30.0% |
| May 2025 | 247 W | 33.9% |
| Jun 2025 | 396 W | 60.5% |

- No reading has load exceeding supply by more than 50 W.
- The 18 readings with zero load still show about 45 W supplied, for example
  on 2025-04-30 from 06:00, with grid about 41 W and PV about 4 W. This is
  the same loss.
- Only 2 readings sit more than 100 W off the loss line:

| Time | Load | Grid | PV | Battery | Gap |
|---|---:|---:|---:|---:|---:|
| 2025-06-28 10:00 | 2,762 W | 0 W | 1,474 W | −1,522 W | 234 W |
| 2025-06-28 10:30 | 3,013 W | 7.7 W | 1.4 W | −3,340 W | 336 W |

Both are at very high battery discharge, where losses are larger, so they may
still be genuine.

**Change made** (decided by Omar, 2026-11-10): none. Readings are not flagged
or removed. Flagging a third of the readings as suspicious would mislabel
good data, and removing them would delete most low-use hours (nights,
spring).

### 4. Lebanese public holidays: list saved, school holidays still missing

**Question.** Which days are public holidays in the periods we use? (Roadmap:
"Add calendar columns: hour, weekday, weekend, school holidays, Lebanese
public holidays".) Hour, weekday and weekend are already given to the
models through the hour-of-week input.

**Sources.** The main source is the official list from Banque du Liban,
covering holidays "observed by the Banque du Liban, its branches, the
banking and financial sectors in Lebanon and the public sector". The live
page has 2025 and 2026, and a Wayback Machine copy from 2024-11-14 has
2024. The Prime Minister's closure memoranda, as reported by LBCI, NNA and
L'Orient Today, confirm final dates and add extra closure days. Islamic
holidays are announced shortly before they happen, so dates taken only from
a list marked "tentative" are given confidence *medium*.

**Result.** 29 dates are in `config/lebanon_public_holidays.csv`, each with
its source link and confidence. They cover August–September 2024,
December 2024 to July 2025 (village sites, including the July test month)
and April–September 2026 (Azm).

- One correction: for the Prophet's Birthday in 2024, Dar al-Fatwa announced
  September 15, while the Banque du Liban tentative list showed September 27.
  We use September 15.
- **Check against Azm's load.** A weekday is "quiet" when its 8 AM–4 PM load
  is below 60% of the median for the same weekday in that month. There are
  11 quiet weekdays from April 16 to August 31, 2026. All 8 official weekday
  holidays in that period are among them, including the 3 marked medium,
  which supports the list.
- Three quiet weekdays are not official holidays:

| Date | Daytime load | Usual | Possible reason, unconfirmed |
|---|---:|---:|---|
| Tue 2026-05-26 | 99 kW | 226 kW | Between Liberation Day (Mon) and Eid (Wed): likely a school bridge day |
| Tue 2026-06-23 | 189 kW | 338 kW | Unknown |
| Tue 2026-08-04 | 79 kW | 214 kW | Port explosion anniversary: official in 2024 and 2025, not on the 2026 list |

These are probably school decisions. They are **not** added as holidays
from the load data itself, because that would be circular. They wait for
Azm's academic calendar, which was not found online and has to be requested
from the school.

**Change made** (decided by Omar, 2026-11-10): the holiday file is saved, and
calendar columns are written for every site and hour in the hourly data. The
columns are hour, weekday, weekend (Saturday/Sunday), public holiday, holiday
name, holiday confidence and school holiday. They go to
`outputs/calendar/hourly_calendar.csv`, built by `scripts/build_calendar.py`,
in a separate file so the existing `hourly_data.csv` and its verifier are
untouched.

- Holiday columns are blank (unknown) outside the researched periods. No data
  hour currently falls outside them.
- School holiday is blank everywhere until Azm's calendar arrives.
- Public-holiday days in the data: Azm 9; Households 1 and 3 and
  Municipality 19; Household 2 18; Industrial sites 15.

The models do not use these columns yet. Whether holiday inputs improve the
forecast is a separate, measured step.

### 5. Azm weather files: download scripted; forecast file not reproducible

**Question.** Can one command re-fetch Azm's weather? (Roadmap: "Script every
weather download (historical and archived forecasts) so one command
re-fetches the exact data".) The data ZIP holds two hand-downloaded
Open-Meteo files covering 2026-04-16 to 2026-09-30, both at Beirut local time:

- `azm_weather_observed.csv.csv`: actual weather.
- `azm_weather_forecast_day1.csv.csv`: the forecast made the day before.
  Its `_previous_day1` columns identify Open-Meteo's Previous Runs API.

**Script.** `python scripts/download_azm_weather.py --archive '<data zip>'`
requests both files with the same settings: the Azm map pin from
`config/sites.json`, the same dates, the same six variables, Beirut local
time and CSV format. It saves them to `outputs/weather_azm/` and writes
`manifest.json`, which records each request, its time, its SHA-256 hash and
an hour-by-hour comparison with the supplied file.

**Result.**

| File | Same grid point | Identical hours | Average difference |
|---|---|---:|---|
| Observed (archive API) | Yes | 4,029 / 4,032 | 0 (3 humidity values differ by 1%) |
| Forecast (Previous Runs API) | Yes | 0 / 4,032 | Temperature 0.99 °C, humidity 5.8%, shortwave 10.2 W/m², cloud 7.6%, diffuse 5.9 W/m², direct 14.6 W/m² |

- **The observed file is reproduced**, so its origin is confirmed.
- **The forecast file cannot be reproduced today.** The default model blend
  (`best_match`) returns the supplied file's grid point, so that is how it was
  made, but the values served now differ. A one-time check, not part of the
  script, requested 16 single models for April 16–30. None matched: at most 1
  of 360 hours was identical. The provider has evidently updated its archive
  since the original download, on a date we do not know. There is no time
  shift between the files: the best alignment is at 0 hours for every
  variable.
- Two downloads on 2026-11-10 gave the same hash, so today's data is stable.
  Reproducibility for the forecast input therefore rests on the saved file
  and its hash, not on re-downloading.
- The Previous Runs service was intermittently unreachable from the AUB
  network. The script reports this and can be re-run with
  `--only forecast`.

**Decision** (Omar, 2026-11-10): the models keep using the **supplied**
forecast file, which is what the existing weather experiments were built on.
The fresh download stays in `outputs/weather_azm/` as a documented
alternative. Whether it gives better forecasts is for the Models stream to
test. No code changed: the pipeline still reads the supplied file from the
data ZIP.

### 6. Azm generator columns: added as a separate hourly file

**Question.** The roadmap asks that the hourly Azm data keep "load,
production, each generator's power and status". The hourly data had only
load and PV.

**Method** (decided by Omar, 2026-11-10). `scripts/build_hourly_generators.py`
reads the four `Generator N Power` and `Generator N Status` columns before
2026-09-01. It applies the same complete-hour rule as the load: exactly one
reading in each 5-minute slot, with every value present. Per hour it writes:

- `G1_kw` to `G4_kw`: mean output;
- `G1_running_share` to `G4_running_share`: share of the hour the unit's
  status was on (0 to 1);
- `configuration`: the running units, for example `G3` or `G1+G4`, or `mixed`
  when they changed during the hour.

The output is `outputs/generators/azm_hourly_generators.csv`, a separate file
so `hourly_data.csv` and its verifier are unchanged.

**Result.** 3,262 complete hours, exactly the same hours as the load data;
32 incomplete hours are excluded.

| Configuration | Hours |
|---|---:|
| G3 | 1,147 |
| G4 | 1,057 |
| G1 | 719 |
| mixed (handover during the hour) | 209 |
| G2 | 120 |
| G1+G4 | 6 |
| G2+G3+G4 | 3 |
| G2+G4 | 1 |

The single-configuration counts equal those in `GENERATORS.md`, which were
computed independently from the same rows. Mixed hours average about 1.5 per
day.

## Every change made to the data

In order of application. The full approved rules are in `BASELINE_PROTOCOL.md`.

1. **Read, never written.** Workbooks are read in memory from the ZIP. The
   archive's SHA-256 is checked before and after every run.
2. **Test months removed first.** Azm rows from 2026-09-01 on (8,589 rows) are
   dropped before any value is used. Each village site's July 2025 workbook
   is not opened.
3. **Timestamps kept as recorded:** Lebanese local time, with no time-zone
   conversion. Slash-formatted dates (day/month or month/day) are resolved
   using the month in the workbook's file name.
4. **Hourly averages, complete hours only.** An hour is kept only when every
   reading slot is present exactly once: 12 five-minute readings for Azm, 2
   half-hour readings for the village sites. Missing hours are never filled
   or bridged, and lag inputs look up exact timestamps.
5. **Bad values rejected, not repaired.** Negative or non-numeric load or PV
   readings make an hour incomplete. Zeros, spikes and steady readings are
   kept (sections 1 and 3).
6. **One meter freeze masked:** Household 3, 2025-04-04 19:30 to 2025-04-05
   04:00 (section 2).
7. **Units:** hourly data stays in source units (kW for Azm, W for the
   village sites). Only the location-only experiment converts W to kW, by a
   fixed factor of 0.001.
8. **Derived values:** Azm net load = campus load − solar PV, in kW, used by the
   P90 model and the generator rule. This is valid because load includes
   solar-served demand and generator output plus PV equals load within 10% in
   98% of readings (`GENERATORS.md`).
9. **Derived files**, kept separate so `hourly_data.csv` is untouched:
   calendar columns (section 4) and hourly generator columns (section 6).
10. **Weather** enters models only as forecasts available at midnight, never as
    observed future weather. Instantaneous and preceding-hour radiation values
    are aligned separately (`MODEL_RESULTS.md`).

## Excluded files and why

The project's results rely on Azm and Household 3 (decided by Omar,
2026-11-10). The pipeline still processes all eight sites, and the teammate's
results for the other six stay in their reports as exploratory. The
roadmap's reasons were checked against the data with
`scripts/data_checks.py` (check 5), comparing non-zero readings only,
because night-time and outage zeros match trivially:

| Site | Roadmap's reason | What the data shows | Status |
|---|---|---|---|
| Household 1 | Duplicates Household 2 | Feb and Mar 2025 are identical to Household 2 for every non-zero load and PV hour; no other month matches | Excluded: confirmed |
| Household 2 | Duplicates; recording change | Same duplicate months. Its monthly median load also jumps: 806 W (Aug 2024), 220 W (Sep), 183 W (Apr 2025), 921 W (May), 967 W (Jun). Household 1 stays between 280 and 554 W. The cause is unknown. | Excluded: confirmed |
| Industrial 1 | Not on the roadmap's list | Normal-looking load (median 242 W, never zero) | Not excluded, but not used in the main results: the roadmap names only Household 3 as the second site |
| Industrial 2 | Copy of Industrial 1 | **Not a copy:** no identical non-zero readings. Its load is almost always near zero (median 0.03 W) with bursts up to 1,258 W. The bursts move with Industrial 1 (correlation 0.88): in its 402 hours above 100 W, Industrial 1's median is 448 W against 242 W overall. Likely a sub-meter, not an independent site. | Excluded: data suspect, though the roadmap's reason was wrong |
| Industrial 3 | Copy of Industrial 1 | **Not a copy.** Median load is 3.1 W with bursts up to 1,207 W, correlated with Industrial 1 (0.86) and Industrial 2 (0.98) | Excluded: data suspect, though the roadmap's reason was wrong |
| Industrial 2, July 2025 | Listed separately | Not checked: July is the final-test month and was not opened | Excluded anyway, since the whole site is excluded |
| Municipality | Listed | Its clock behaves differently from the other six sites at the March 2025 change (`VILLAGE_CLOCK_INSPECTION.md`). Its monthly median load swings from 11 W (Jan) to 404 W (Feb), 22 W (Apr) and 683 W (May). | Excluded: confirmed |

Household 3, by contrast, has a plausible seasonal pattern: monthly median
load of 646 W in August 2024, 209 W in April 2025 and 403 W in June 2025. It
has one masked freeze (section 2) and a consistent power balance (section 3).

## Weather files and other supplied material

| Material | Where it comes from | Used? | Known limits |
|---|---|---|---|
| Azm observed weather (`azm_weather_observed.csv.csv`) | Open-Meteo archive API at the Azm pin, Beirut time; reproduced by `scripts/download_azm_weather.py` | For checks only, never as a model input | Grid point 34.411, 35.887, a few km from the campus |
| Azm forecast weather (`azm_weather_forecast_day1.csv.csv`) | Open-Meteo Previous Runs API, default blend, forecast made the day before | Yes, in the "with forecast weather" experiments (the supplied copy, section 5) | Exact publication time unverified; cannot be re-downloaded identically |
| Village forecast weather | Open-Meteo Previous Runs API at the village point, via `scripts/download_village_weather.py` | Location-only experiment only; Household 3's models do not use weather yet | Cached on the teammate's machine only (`outputs/` is not in Git); intermittently blocked on AUB's network |
| Building Data Genome Project 2 (595 MB ZIP) | Open dataset of hourly building meters, 2016–2017 | No. Optional pretraining idea in the roadmap | Not opened |
| `El Qlaiaat history_export 2018.xlsx` | 2018 weather workbook | No | Not checked |
| `LebanonSystem.xlsx`, `220 kV Network.doc`, `Data_year_karoun.m`, `IEEE9.txt` | Regional power-system material; Karoun 2016 is the roadmap's stretch goal | No | Not checked |

## Publication permission

Not established. Whether the school allows its data to be published in a
public GitHub repository has not been confirmed to us. Until it is:

- no measurements are committed: the ZIP, `data/` and `outputs/` are
  git-ignored;
- reports contain only summaries, such as error scores, capacities and
  monthly medians.

If permission is refused, the roadmap's fallback applies: commit an
anonymised sample and document how to request the full data.

## Open items

| Item | Who | Why it matters |
|---|---|---|
| Azm's 2025–26 academic calendar | Ask the school | Fills the school-holiday column; explains the quiet days of May 26, Jun 23 and Aug 4 (section 4) |
| Permission to publish the data | Ask the school | Decides whether data or only a sample can go on GitHub |
| How generators are chosen today | Ask the school | The current practice is so far inferred from status columns (`GENERATORS.md`) |
| Whether Azm's morning start moved from 6 AM to 7 AM on June 29 | Ask the school | Confirms the timetable change seen in section 1 |
| What changed in Household 2's recording | Data provider, if needed | Only matters if Household 2 is ever used again |

"""Reproduce the data checks recorded in DATA_PROVENANCE.md (roadmap Week 1, stream A).

Check 1: Azm hourly load jumps above 200 kW (April 16 to August 31, 2026).
Check 2: Household 3 readings stuck on one value for 3 hours or more.
Check 3: Household 3 power balance, grid + PV - battery against load.

Final test months are never read: September 2026 for Azm, July 2025 for the
village sites. Nothing is changed in the data; results are written to
outputs/data_checks/.
"""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
from zipfile import ZipFile

from ..data.preparation import _site_records, file_sha256, mask_frozen_readings
from ..data.calendar_days import load_public_holidays
from ..generators.capacity import GENERATOR_IDS, _number, _quantile, read_records as read_azm_records

AZM_END = datetime(2026, 9, 1)
VILLAGE_END = datetime(2025, 7, 1)
HH3_COLUMNS = {"load": "Load power (w)", "grid": "Grid power (w)", "pv": "PV power (w)", "battery": "Battery power (w)"}
HOUR = timedelta(hours=1)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _mean(values):
    return sum(values) / len(values) if values else None


# ---------------------------------------------------------------- check 1

def hourly_summary(readings):
    """readings: (timestamp, load, pv, generator_total). One summary per clock hour."""
    buckets = defaultdict(list)
    for row in sorted(readings, key=lambda item: item[0]):
        buckets[row[0].replace(minute=0, second=0, microsecond=0)].append(row)
    summary = {}
    for hour, rows in buckets.items():
        loads = [load for _, load, _, _ in rows if load is not None]
        if not loads:
            continue
        summary[hour] = {
            "readings": len(loads),
            "mean": _mean(loads), "last": loads[-1], "max": max(loads), "min": min(loads),
            "pv": _mean([pv for _, _, pv, _ in rows if pv is not None]),
            "generators": _mean([gen for _, _, _, gen in rows if gen is not None]),
            "net": _mean([load - pv for _, load, pv, _ in rows if load is not None and pv is not None]),
        }
    return summary


def _changes(series, lag):
    return {hour: value - series[hour - lag] for hour, value in series.items()
            if value is not None and series.get(hour - lag) is not None}


def count_jumps(readings, threshold_kw=200.0):
    """Count load jumps under ten definitions and list the main-definition jumps."""
    hours = hourly_summary(readings)
    column = lambda key: {hour: stats[key] for hour, stats in hours.items()}
    mean = column("mean")
    ordered = sorted(mean)
    loads = [load for _, load, _, _ in sorted(readings, key=lambda item: item[0]) if load is not None]
    big = lambda changes: sum(abs(change) > threshold_kw for change in changes.values())
    definitions = {
        "hourly mean vs previous clock hour (main definition)": big(_changes(mean, HOUR)),
        "hourly mean vs previous available hour (across gaps)":
            sum(abs(mean[b] - mean[a]) > threshold_kw for a, b in zip(ordered, ordered[1:])),
        "last reading of each hour vs previous hour": big(_changes(column("last"), HOUR)),
        "hourly maximum vs previous hour": big(_changes(column("max"), HOUR)),
        "one 5-minute reading vs the next": sum(abs(b - a) > threshold_kw for a, b in zip(loads, loads[1:])),
        "maximum minus minimum inside one hour": sum(s["max"] - s["min"] > threshold_kw for s in hours.values()),
        "hourly mean vs same hour yesterday": big(_changes(mean, 24 * HOUR)),
        "hourly mean, change over 2 hours": big(_changes(mean, 2 * HOUR)),
        "hourly net load (load - PV) vs previous hour": big(_changes(column("net"), HOUR)),
        "hours where load crosses above the threshold":
            sum(value > threshold_kw and mean.get(hour - HOUR) is not None and mean[hour - HOUR] <= threshold_kw
                for hour, value in mean.items()),
    }
    jumps = []
    for hour, change in sorted(_changes(mean, HOUR).items()):
        if abs(change) <= threshold_kw:
            continue
        before, now = hours[hour - HOUR], hours[hour]
        d_generators, d_pv = now["generators"] - before["generators"], now["pv"] - before["pv"]
        jumps.append({"hour": hour.isoformat(), "weekday": WEEKDAYS[hour.weekday()], "load_kw": now["mean"],
                      "load_change_kw": change, "generator_change_kw": d_generators, "pv_change_kw": d_pv,
                      "generators_plus_pv_match": abs(d_generators + d_pv - change) <= 0.15 * abs(change)})
    return {"threshold_kw": threshold_kw, "hours_with_data": len(hours), "definitions": definitions,
            "main_definition_jumps": jumps,
            "summary": {"count": len(jumps), "increases": sum(j["load_change_kw"] > 0 for j in jumps),
                        "by_clock_hour": dict(Counter(j["hour"][11:16] for j in jumps)),
                        "by_weekday": dict(Counter(j["weekday"] for j in jumps)),
                        "by_month": dict(Counter(j["hour"][:7] for j in jumps)),
                        "confirmed_by_generator_meters": sum(j["generators_plus_pv_match"] for j in jumps)}}


# ---------------------------------------------------------------- check 2

def stuck_runs(rows, channels, *, step, minimum_readings):
    """Per channel, runs of at least minimum_readings identical non-zero values, step apart."""
    rows = sorted(rows, key=lambda item: item[0])
    found = []
    for channel in channels:
        start = 0
        for index in range(1, len(rows) + 1):
            value = rows[start][1].get(channel)
            if (index < len(rows) and value is not None and rows[index][0] - rows[index - 1][0] == step
                    and rows[index][1].get(channel) == value):
                continue
            length = index - start
            if value is not None and value != 0 and length >= minimum_readings:
                found.append({"channel": channel, "start": rows[start][0].isoformat(),
                              "end": rows[index - 1][0].isoformat(), "readings": length, "value": value})
            start = index
    stretches = defaultdict(dict)
    for run in found:
        stretches[(run["start"], run["end"], run["readings"])][run["channel"]] = run["value"]
    result = []
    for (start, end, readings), values in sorted(stretches.items()):
        inside = [v for stamp, v in rows if start <= stamp.isoformat() <= end]
        constant = {c: inside[0].get(c) for c in channels if len({v.get(c) for v in inside}) == 1}
        result.append({"start": start, "end": end, "readings": readings, "stuck_nonzero_channels": values,
                       "constant_channels_including_zero": constant,
                       "all_channels_constant": set(constant) == set(channels)})
    return result


# ---------------------------------------------------------------- check 3

def power_balance(rows, *, agreement=0.20, outlier_w=100.0):
    """rows: (timestamp, {load, grid, pv, battery}) with all four values present."""
    import numpy as np

    if not rows:
        raise ValueError("No complete readings to check")
    loads = np.array([v["load"] for _, v in rows])
    supplied = np.array([v["grid"] + v["pv"] - v["battery"] for _, v in rows])
    opposite = np.array([v["grid"] + v["pv"] + v["battery"] for _, v in rows])
    gap = supplied - loads
    positive = loads > 0
    within = lambda total, share: float(np.mean(np.abs(total[positive] - loads[positive]) <= share * loads[positive]))
    slope, intercept = np.polyfit(loads, gap, 1)
    residual = gap - (intercept + slope * loads)
    monthly = defaultdict(list)
    for (stamp, _), load, difference in zip(rows, loads, gap):
        if load > 0:  # monthly table uses the same readings as the 20% rule
            monthly[stamp.strftime("%Y-%m")].append((float(load), float(difference)))
    months = {}
    for month, values in sorted(monthly.items()):
        months[month] = {"readings_with_load": len(values),
                         "median_load_w": _quantile([l for l, _ in values], 0.5),
                         "median_gap_w": _quantile([d for _, d in values], 0.5),
                         "within_20pct_share": sum(abs(d) <= agreement * l for l, d in values) / len(values)}
    outliers = [{"time": stamp.isoformat(), **values, "gap_w": float(difference)}
                for (stamp, values), difference, off in zip(rows, gap, residual) if abs(off) > outlier_w]
    quantiles = {f"p{int(q * 100):02d}": float(np.quantile(gap, q)) for q in (0.05, 0.25, 0.5, 0.75, 0.95)}
    return {"readings": len(rows), "zero_load_readings": int(np.sum(loads == 0)),
            "within_20pct_share": within(supplied, agreement), "within_10pct_share": within(supplied, 0.10),
            "opposite_sign_within_20pct_share": within(opposite, agreement),
            "gap_w_quantiles": quantiles, "fitted_gap": {"fixed_w": float(intercept), "share_of_load": float(slope)},
            "load_exceeds_supply_by_over_50w": int(np.sum(gap < -50)),
            "readings_over_100w_off_fit": outliers, "by_month": months}


# ---------------------------------------------------------------- check 4

def quiet_weekdays(hourly_means, *, first_hour=8, end_hour=16, minimum_hours=6, share=0.6):
    """Monday-Friday days whose daytime load is below `share` of the usual.

    Daytime = first_hour to end_hour (8 AM-4 PM), from complete hours only.
    Usual = median of the same weekday in the same month, excluding the day.
    """
    from statistics import median

    daytime = defaultdict(list)
    for hour, value in hourly_means.items():
        if first_hour <= hour.hour < end_hour:
            daytime[hour.date()].append(value)
    daily = {day: _mean(values) for day, values in daytime.items() if len(values) >= minimum_hours}
    quiet = []
    for day, value in sorted(daily.items()):
        if day.weekday() > 4:
            continue
        peers = [v for d, v in daily.items() if d != day and d.month == day.month and d.weekday() == day.weekday()]
        if peers and value < share * median(peers):
            quiet.append({"date": day.isoformat(), "weekday": WEEKDAYS[day.weekday()],
                          "daytime_load_kw": value, "usual_kw": median(peers)})
    return daily, quiet


def holidays_versus_quiet_days(daily, quiet, holidays):
    """Which official weekday holidays were quiet, and which quiet days are unexplained."""
    quiet_dates = {item["date"] for item in quiet}
    official = []
    for day, row in sorted(holidays.items()):
        if day in daily and day.weekday() <= 4:
            official.append({"date": day.isoformat(), "name": row["name"], "confidence": row["confidence"],
                             "quiet": day.isoformat() in quiet_dates})
    listed = {day.isoformat() for day in holidays}
    return {"official_weekday_holidays_in_data": official,
            "official_holidays_that_were_quiet": sum(item["quiet"] for item in official),
            "quiet_days_not_official_holidays": [item for item in quiet if item["date"] not in listed]}


# ---------------------------------------------------------------- check 5

def read_hourly_series(hourly_csv):
    """{(site_id, target): {hour: value}} from the pipeline's hourly_data.csv."""
    series = defaultdict(dict)
    with Path(hourly_csv).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            series[(row["site_id"], row["target"])][datetime.fromisoformat(row["timestamp_local_unverified"])] = \
                float(row["value_source_units"])
    return series


def compare_village_sites(series, sites, *, minimum_identical_share=0.01):
    """Evidence for the roadmap's exclusion list: copied months, level changes, odd industrial loads."""
    import numpy as np
    from statistics import median

    copies = []
    for target in ("load", "pv"):
        for i, a in enumerate(sites):
            for b in sites[i + 1:]:
                x, y = series.get((a, target), {}), series.get((b, target), {})
                both = [t for t in set(x) & set(y) if x[t] != 0 and y[t] != 0]  # zeros (night, outages) match trivially
                same = {t for t in both if x[t] == y[t]}
                if both and len(same) / len(both) > minimum_identical_share:
                    months = defaultdict(lambda: [0, 0])
                    for t in both:
                        months[t.strftime("%Y-%m")][0] += 1
                        months[t.strftime("%Y-%m")][1] += t in same
                    copies.append({"target": target, "sites": [a, b], "identical_nonzero_hours": len(same),
                                   "nonzero_hours_in_both": len(both),
                                   "identical_share_by_month": {m: s / n for m, (n, s) in sorted(months.items()) if s}})
    monthly_median_load = {}
    for site in sites:
        months = defaultdict(list)
        for t, value in series.get((site, "load"), {}).items():
            months[t.strftime("%Y-%m")].append(value)
        monthly_median_load[site] = {m: median(v) for m, v in sorted(months.items())}
    industrial = [s for s in sites if s.startswith("industrial")]
    loads = {s: series[(s, "load")] for s in industrial}
    common = sorted(set.intersection(*(set(v) for v in loads.values()))) if loads else []
    matrix = np.array([[loads[s][t] for t in common] for s in industrial]) if common else None
    profile = {s: {"zero_share": float(np.mean(np.array(list(v.values())) == 0)),
                   "median_w": float(np.median(list(v.values()))),
                   "p95_w": float(np.percentile(list(v.values()), 95)), "max_w": float(max(v.values()))}
               for s, v in loads.items()}
    correlations = {f"{a} vs {b}": float(np.corrcoef(matrix[i], matrix[j])[0, 1])
                    for i, a in enumerate(industrial) for j, b in enumerate(industrial) if i < j} if common else {}
    together = None
    if {"industrial_1", "industrial_2"} <= set(industrial):
        busy = [t for t in common if loads["industrial_2"][t] > 100]
        together = {"hours_industrial_2_above_100w": len(busy),
                    "industrial_1_median_in_those_hours_w": float(np.median([loads["industrial_1"][t] for t in busy])) if busy else None,
                    "industrial_1_median_overall_w": profile["industrial_1"]["median_w"]}
    return {"identical_nonzero_readings": copies, "monthly_median_load_w": monthly_median_load,
            "industrial_load_profile": profile, "industrial_load_correlation": correlations,
            "industrial_2_bursts": together}


# ---------------------------------------------------------------- run

def _household_3_rows(archive_path, site):
    counters = {"timestamp_interpretations": Counter(), "positive_intervals_seconds": Counter(),
                "reserved_or_later_rows_not_used": 0, "workbooks_read": 0, "reserved_workbooks_not_opened": []}
    profile = {"validation_end_exclusive": VILLAGE_END.isoformat(), "targets": HH3_COLUMNS}
    with ZipFile(archive_path) as archive:
        rows = [(stamp, {k: _number(v) for k, v in values.items()})
                for stamp, values in _site_records(archive, site, profile, counters)]
    return rows, counters["reserved_workbooks_not_opened"]


def run(archive_path, sites, frozen_rule, hourly_csv=None):
    by_id = {site["site_id"]: site for site in sites}
    village_ids = [site["site_id"] for site in sites if site["site_id"] != "azm"]
    azm = []
    for stamp, values in read_azm_records(archive_path, by_id["azm"], AZM_END):
        generators = [values.get(f"{g}_kw") for g in GENERATOR_IDS]
        azm.append((stamp, values.get("load"), values.get("pv"),
                    sum(g for g in generators if g is not None)))
    rows, unopened = _household_3_rows(archive_path, by_id["household_3"])
    masked, masked_stretches = mask_frozen_readings(
        rows, targets={"load": None, "pv": None}, sampling_minutes=30,
        minimum_consecutive_readings=frozen_rule["minimum_consecutive_readings"])
    complete = [(stamp, values) for stamp, values in masked if all(values.get(c) is not None for c in HH3_COLUMNS)]
    complete_hours = {hour: s["mean"] for hour, s in hourly_summary(azm).items() if s["readings"] == 12}
    daily, quiet = quiet_weekdays(complete_hours)
    return {"source_sha256": file_sha256(archive_path),
            "periods": {"azm": f"before {AZM_END.date()}", "household_3": f"before {VILLAGE_END.date()}",
                        "household_3_test_workbooks_not_opened": unopened},
            "check_1_azm_jumps": count_jumps(azm),
            "check_2_household_3_stuck_readings": {
                "stretches": stuck_runs(rows, list(HH3_COLUMNS), step=timedelta(minutes=30), minimum_readings=6),
                "masked_by_pipeline_rule": masked_stretches},
            "check_3_household_3_power_balance": power_balance(complete),
            "check_4_azm_holidays": {"quiet_weekdays": quiet,
                                     **holidays_versus_quiet_days(daily, quiet, load_public_holidays())},
            "check_5_village_site_comparison": (
                {"hourly_data_sha256": file_sha256(hourly_csv),
                 **compare_village_sites(read_hourly_series(hourly_csv), village_ids)}
                if hourly_csv and Path(hourly_csv).is_file() else
                {"skipped": "run scripts/run_baselines.py first to create hourly_data.csv"})}


def _summary(report):
    jumps, stuck, balance = (report["check_1_azm_jumps"], report["check_2_household_3_stuck_readings"],
                             report["check_3_household_3_power_balance"])
    lines = ["# Data checks", "", "Generated by `scripts/data_checks.py`. See DATA_PROVENANCE.md for interpretation.", "",
             "## 1. Azm load jumps above 200 kW", "",
             f"Main definition: {jumps['summary']['count']} jumps, {jumps['summary']['increases']} increases, "
             f"{jumps['summary']['confirmed_by_generator_meters']} confirmed by generator meters.",
             f"By clock hour: {jumps['summary']['by_clock_hour']}; by month: {jumps['summary']['by_month']}.", "",
             "| Definition | Count |", "| --- | ---: |"]
    lines += [f"| {name} | {count} |" for name, count in jumps["definitions"].items()]
    lines += ["", "## 2. Household 3 stuck readings (6+ identical non-zero half-hours)", "",
              "| Start | End | Readings | Constant channels | All four constant? |", "| --- | --- | ---: | --- | --- |"]
    lines += [f"| {s['start']} | {s['end']} | {s['readings']} | {s['constant_channels_including_zero']} | "
              f"{s['all_channels_constant']} |" for s in stuck["stretches"]]
    lines += ["", f"Masked by the pipeline rule: {len(stuck['masked_by_pipeline_rule'])} stretch(es).", "",
              "## 3. Household 3 power balance", "",
              f"{balance['readings']} readings; within 20%: {balance['within_20pct_share']:.1%} "
              f"(opposite battery sign: {balance['opposite_sign_within_20pct_share']:.1%}).",
              f"Gap = {balance['fitted_gap']['fixed_w']:.0f} W + {balance['fitted_gap']['share_of_load']:.1%} of load; "
              f"median gap {balance['gap_w_quantiles']['p50']:.0f} W.",
              f"Readings more than 100 W off that line: {len(balance['readings_over_100w_off_fit'])}.", "",
              "| Month | Median load (W) | Median gap (W) | Within 20% |", "| --- | ---: | ---: | ---: |"]
    lines += [f"| {m} | {v['median_load_w']:.0f} | {v['median_gap_w']:.0f} | {v['within_20pct_share']:.1%} |"
              for m, v in balance["by_month"].items()]
    holidays = report["check_4_azm_holidays"]
    official = holidays["official_weekday_holidays_in_data"]
    lines += ["", "## 4. Azm quiet weekdays and official holidays", "",
              f"Official weekday holidays in the data: {len(official)}; quiet that day: "
              f"{holidays['official_holidays_that_were_quiet']}.", "",
              "| Date | Holiday | Confidence | Quiet? |", "| --- | --- | --- | --- |"]
    lines += [f"| {h['date']} | {h['name']} | {h['confidence']} | {h['quiet']} |" for h in official]
    lines += ["", "Quiet weekdays (daytime load below 60% of usual) that are not official holidays:", "",
              "| Date | Weekday | Daytime load (kW) | Usual (kW) |", "| --- | --- | ---: | ---: |"]
    lines += [f"| {q['date']} | {q['weekday']} | {q['daytime_load_kw']:.0f} | {q['usual_kw']:.0f} |"
              for q in holidays["quiet_days_not_official_holidays"]]
    village = report["check_5_village_site_comparison"]
    lines += ["", "## 5. Village sites compared (evidence for the exclusion list)", ""]
    if "skipped" in village:
        return "\n".join(lines + [village["skipped"]]) + "\n"
    lines += ["Identical non-zero readings between sites:", ""]
    lines += [f"- {c['target']} {c['sites'][0]} vs {c['sites'][1]}: {c['identical_nonzero_hours']}/"
              f"{c['nonzero_hours_in_both']} hours; by month "
              + ", ".join(f"{m} {s:.0%}" for m, s in c["identical_share_by_month"].items())
              for c in village["identical_nonzero_readings"]]
    lines += ["", "Monthly median load (W):", ""]
    lines += [f"- {site}: " + ", ".join(f"{m} {v:.1f}" for m, v in months.items())
              for site, months in village["monthly_median_load_w"].items()]
    lines += ["", "Industrial loads:", ""]
    lines += [f"- {s}: zero {p['zero_share']:.0%}, median {p['median_w']:.4g} W, 95th percentile {p['p95_w']:.0f} W, "
              f"max {p['max_w']:.0f} W" for s, p in village["industrial_load_profile"].items()]
    lines += [f"- correlation {pair}: {value:.3f}" for pair, value in village["industrial_load_correlation"].items()]
    burst = village["industrial_2_bursts"]
    if burst:
        lines.append(f"- when industrial_2 load > 100 W ({burst['hours_industrial_2_above_100w']} hours), industrial_1 "
                     f"median is {burst['industrial_1_median_in_those_hours_w']:.0f} W vs {burst['industrial_1_median_overall_w']:.0f} W overall")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sites", type=Path, default=Path("config/sites.json"))
    parser.add_argument("--baseline-config", type=Path, default=Path("config/baseline.json"))
    parser.add_argument("--hourly-data", type=Path, default=Path("outputs/baselines_confirmed_azm/hourly_data.csv"),
                        help="Pipeline hourly data, used by check 5")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/data_checks"))
    args = parser.parse_args()
    sites = json.loads(args.sites.read_text(encoding="utf-8"))["sites"]
    frozen_rule = json.loads(args.baseline_config.read_text(encoding="utf-8"))["frozen_readings"]
    report = run(args.archive, sites, frozen_rule, args.hourly_data)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = _summary(report)
    (args.output_dir / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    print(f"Saved {args.output_dir / 'results.json'} and summary.md")

"""Where the served forecast goes wrong: errors by condition and the worst days.

Reads the rolling-origin predictions (models/walk_forward.py), so every
forecast scored here was made at midnight from earlier data only. The
served point method is compared with the best baseline on the same hours.
Roadmap Week 3: "errors by hour, weekday vs. weekend, hot vs. mild days,
holidays; pick 3 worst days and explain them". September is not read.

The one-line explanations of the worst days are assembled from measured
facts (holiday, level against the week before, size and direction of the
miss). They describe what happened in the data; they are not confirmed
causes.
"""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from statistics import median

from ..data.calendar_days import load_public_holidays
from ..data.preparation import file_sha256

POINT, UPPER, BASELINE = "ridge_holiday", "ridge_holiday_plus_recent_errors", "last_week"


def read_predictions(path):
    rows = {}
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            values = {name: float(row[name]) if row.get(name) not in (None, "") else None
                      for name in ("actual", POINT, UPPER, BASELINE)}
            rows[datetime.fromisoformat(row["timestamp_local"])] = values
    return rows


def read_daily_peak_temperature(path):
    """{date: highest forecast temperature of the day} from the aligned forecast-weather file."""
    peaks = {}
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            day = datetime.fromisoformat(row["timestamp_local"]).date()
            peaks[day] = max(peaks.get(day, -math.inf), float(row["forecast_temperature"]))
    return peaks


def _group_scores(rows):
    """rows are (actual, forecast, baseline, upper)."""
    if not rows:
        return None
    count = len(rows)
    mean_abs_actual = math.fsum(abs(a) for a, _, _, _ in rows) / count
    mae = math.fsum(abs(a - f) for a, f, _, _ in rows) / count
    baseline_mae = math.fsum(abs(a - b) for a, _, b, _ in rows) / count
    return {"hours": count, "mean_actual_kw": math.fsum(a for a, _, _, _ in rows) / count,
            "mae_kw": mae, "nmae": mae / mean_abs_actual if mean_abs_actual else None,
            "bias_kw": math.fsum(f - a for a, f, _, _ in rows) / count,
            "baseline_mae_kw": baseline_mae,
            "baseline_nmae": baseline_mae / mean_abs_actual if mean_abs_actual else None,
            "upper_coverage": sum(a <= u for a, _, _, u in rows) / count,
            "hours_above_upper": sum(a > u for a, _, _, u in rows)}


def analyse(predictions, holidays, peak_temperature=None):
    scored = {stamp: values for stamp, values in predictions.items()
              if all(values[name] is not None for name in ("actual", POINT, UPPER, BASELINE))}
    if not scored:
        raise ValueError("No hours carry the actual, the served forecast, its upper estimate and the baseline")

    def rows_where(test):
        return [(v["actual"], v[POINT], v[BASELINE], v[UPPER]) for stamp, v in sorted(scored.items()) if test(stamp)]

    after_holiday = {day + timedelta(days=1) for day in holidays} - set(holidays)
    groups = {
        "by_month": {month: _group_scores(rows_where(lambda s, m=month: s.strftime("%B") == m))
                     for month in dict.fromkeys(stamp.strftime("%B") for stamp in sorted(scored))},
        "by_hour": {f"{hour:02d}:00": _group_scores(rows_where(lambda s, h=hour: s.hour == h)) for hour in range(24)},
        "by_day_type": {
            "weekday (Mon-Fri)": _group_scores(rows_where(lambda s: s.weekday() < 5 and s.date() not in holidays)),
            "weekend (Sat-Sun)": _group_scores(rows_where(lambda s: s.weekday() >= 5 and s.date() not in holidays)),
            "public holiday": _group_scores(rows_where(lambda s: s.date() in holidays)),
            "day after a holiday": _group_scores(rows_where(lambda s: s.date() in after_holiday))},
        "by_load_level": {
            "working hours (07:00-16:59, Mon-Fri)": _group_scores(
                rows_where(lambda s: s.weekday() < 5 and 7 <= s.hour < 17 and s.date() not in holidays)),
            "all other hours": _group_scores(
                rows_where(lambda s: not (s.weekday() < 5 and 7 <= s.hour < 17 and s.date() not in holidays)))},
    }
    if peak_temperature:
        days = sorted({stamp.date() for stamp in scored if stamp.date() in peak_temperature})
        split = median(peak_temperature[day] for day in days)
        groups["by_forecast_temperature"] = {
            f"hot days (forecast peak above {split:.1f} C)": _group_scores(
                rows_where(lambda s: s.date() in peak_temperature and peak_temperature[s.date()] > split)),
            f"mild days (forecast peak up to {split:.1f} C)": _group_scores(
                rows_where(lambda s: s.date() in peak_temperature and peak_temperature[s.date()] <= split))}
    return {"hours": len(scored), "first_hour": min(scored).isoformat(), "last_hour": max(scored).isoformat(),
            "overall": _group_scores(rows_where(lambda s: True)), "groups": groups,
            "worst_days": worst_days(scored, predictions, holidays)}


def worst_days(scored, predictions, holidays, count=3):
    by_day = {}
    for stamp, values in scored.items():
        by_day.setdefault(stamp.date(), []).append((stamp, values))
    complete = {day: sorted(rows) for day, rows in by_day.items() if len(rows) == 24}
    ranked = sorted(complete, key=lambda day: -math.fsum(abs(v["actual"] - v[POINT]) for _, v in complete[day]))
    results = []
    for day in ranked[:count]:
        rows = complete[day]
        actual = [v["actual"] for _, v in rows]
        forecast = [v[POINT] for _, v in rows]
        errors = [f - a for a, f in zip(actual, forecast)]
        worst = max(range(24), key=lambda index: abs(errors[index]))
        # Typical level: the same weekday in the four weeks before, skipping holidays and incomplete days.
        typical = []
        for weeks in range(1, 5):
            earlier = day - timedelta(days=7 * weeks)
            values = [predictions.get(stamp - timedelta(days=7 * weeks), {}).get("actual") for stamp, _ in rows]
            if earlier not in holidays and all(value is not None for value in values):
                typical.append(math.fsum(values) / 24)
        level_change = (math.fsum(actual) / 24) / (math.fsum(typical) / len(typical)) - 1 if typical else None
        facts = {"date": day.isoformat(), "weekday": day.strftime("%A"),
                 "mae_kw": math.fsum(abs(e) for e in errors) / 24,
                 "baseline_mae_kw": math.fsum(abs(v["actual"] - v[BASELINE]) for _, v in rows) / 24,
                 "mean_actual_kw": math.fsum(actual) / 24, "mean_forecast_kw": math.fsum(forecast) / 24,
                 "actual_peak_kw": max(actual), "forecast_peak_kw": max(forecast),
                 "worst_hour": rows[worst][0].strftime("%H:%M"), "worst_hour_error_kw": errors[worst],
                 "hours_above_upper": sum(v["actual"] > v[UPPER] for _, v in rows),
                 "is_public_holiday": day in holidays,
                 "day_before_is_holiday": day - timedelta(days=1) in holidays,
                 "week_before_is_holiday": day - timedelta(days=7) in holidays,
                 "level_against_typical_weekday": level_change}
        facts["explanation"] = explain(facts)
        results.append(facts)
    return results


def explain(facts):
    direction = "under" if facts["mean_forecast_kw"] < facts["mean_actual_kw"] else "over"
    parts = []
    if facts["is_public_holiday"]:
        parts.append("public holiday")
    if facts["day_before_is_holiday"]:
        parts.append("the day after a public holiday")
    if facts["week_before_is_holiday"]:
        parts.append("the same day last week was a holiday")
    change = facts["level_against_typical_weekday"]
    if change is not None and abs(change) >= 0.15:
        parts.append(f"the day ran {abs(change):.0%} {'above' if change > 0 else 'below'} "
                     f"a typical {facts['weekday']} of the previous four weeks")
    context = "; ".join(parts) if parts else "no holiday and close to a typical day overall"
    return (f"{direction.capitalize()}-forecast: peak {facts['actual_peak_kw']:.0f} kW against "
            f"{facts['forecast_peak_kw']:.0f} kW forecast, largest miss {abs(facts['worst_hour_error_kw']):.0f} kW "
            f"at {facts['worst_hour']} ({context}).")


def summary_markdown(report):
    def table(title, groups):
        lines = [f"## {title}", "",
                 "| Group | Hours | Mean load (kW) | nMAE | Baseline nMAE | Bias (kW) | Hours above upper estimate |",
                 "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for name, scores in groups.items():
            if scores is None:
                continue
            lines.append(f"| {name} | {scores['hours']} | {scores['mean_actual_kw']:.0f} | {scores['nmae']:.1%} | "
                         f"{scores['baseline_nmae']:.1%} | {scores['bias_kw']:+.1f} | "
                         f"{scores['hours_above_upper']} ({1 - scores['upper_coverage']:.1%}) |")
        return lines + [""]

    analysis = report["analysis"]
    lines = ["# Error analysis (Azm net load, rolling-origin forecasts)", "",
             f"{analysis['hours']} hours, {analysis['first_hour'][:10]} to {analysis['last_hour'][:10]}. "
             f"Forecast: `{POINT}`; baseline: `{BASELINE}`; upper estimate: `{UPPER}`. "
             "Bias is forecast minus actual, so negative means under-forecast. September is not read.", ""]
    lines += table("Overall", {"all hours": analysis["overall"]})
    titles = {"by_month": "By month", "by_day_type": "By type of day", "by_load_level": "Working hours vs. the rest",
              "by_forecast_temperature": "Hot vs. mild days", "by_hour": "By hour of day"}
    for key, title in titles.items():
        if key in analysis["groups"]:
            lines += table(title, analysis["groups"][key])
    lines += ["## Three worst days", ""]
    for day in analysis["worst_days"]:
        lines.append(f"- **{day['weekday']} {day['date']}** (error {day['mae_kw']:.0f} kW on average; "
                     f"baseline {day['baseline_mae_kw']:.0f} kW; {day['hours_above_upper']} hours above the "
                     f"upper estimate). {day['explanation']}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--predictions", type=Path, default=Path("outputs/walk_forward/predictions.csv"))
    parser.add_argument("--weather-features", type=Path, default=Path("outputs/weather_features/features.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/error_analysis"))
    args = parser.parse_args()
    temperature = read_daily_peak_temperature(args.weather_features) if args.weather_features.is_file() else None
    report = {"run_time_utc": datetime.now(timezone.utc).isoformat(), "site_id": "azm",
              "predictions_sha256": file_sha256(args.predictions), "test_period_scored": False,
              "analysis": analyse(read_predictions(args.predictions), set(load_public_holidays()), temperature)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    (args.output_dir / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
    print(summary_markdown(report))


if __name__ == "__main__":
    main()

"""Real-world constraint: what happens when inputs are missing on the day?

Every validation day is forecast through the same function the API serves,
once with full history and once per missing-input scenario, with and
without the fallbacks. Scores: net-load error, coverage of the upper
estimate, wrong-generator hours, and hours left without any forecast.

Weather is not an input of the served model (it did not reduce the error,
WEEK2_RESULTS.md), so "weather forecast missing" changes nothing here; the
report states that rather than simulating it. September is never read.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

from ..api.service import ForecastRequest, Reading, forecast
from ..data.preparation import file_sha256
from ..generators.policy import Generator, pick_errors
from ..models.ridge import load_inputs

# Hours of meter data lost immediately before the midnight issue time.
SCENARIOS = {"full_inputs": 0, "last_6_hours_missing": 6, "last_24_hours_missing": 24,
             "last_8_days_missing": 192, "no_meter_history": None}


def build_request(load, pv, issue, missing_hours, apply_fallbacks=True):
    """Readings completed before `issue`, minus the last `missing_hours` (None = no readings)."""
    if missing_hours is None:
        readings = []
    else:
        cutoff = issue - timedelta(hours=missing_hours)
        readings = [Reading(timestamp_local=stamp, load_kw=load.get(stamp), pv_kw=pv.get(stamp))
                    for stamp in sorted(load.keys() | pv.keys()) if stamp < cutoff]
    return ForecastRequest(issue_time_local=issue, readings=readings, apply_fallbacks=apply_fallbacks)


def evaluate(bundle, load, pv, first_day, end_day):
    policy = bundle["generator_policy"]
    generators = [Generator(item["generator_id"], float(item["usable_capacity_kw"])) for item in policy["generators"]]
    allowed = policy["allowed_configurations"]
    results = {}
    for scenario, missing in SCENARIOS.items():
        for fallbacks in (True, False):
            if scenario == "full_inputs" and not fallbacks:
                continue
            actual, point, upper, picks, methods = [], [], [], [], {}
            observed_hours, without_forecast, switches, days = 0, 0, 0, 0
            day = first_day
            while day < end_day:
                response = forecast(bundle, build_request(load, pv, day, missing, fallbacks))
                capacities = [row["generator"]["capacity_kw"] for row in response["hourly"]]
                switches += sum(a != b for a, b in zip(capacities, capacities[1:]))
                days += 1
                for row in response["hourly"]:
                    stamp = datetime.fromisoformat(row["timestamp_local"])
                    if stamp not in load or stamp not in pv:
                        continue
                    observed_hours += 1
                    methods[row["net_method"]] = methods.get(row["net_method"], 0) + 1
                    if row["net_upper_kw"] is None:
                        without_forecast += 1
                        continue
                    actual.append(load[stamp] - pv[stamp])
                    point.append(row["net_kw"])
                    upper.append(row["net_upper_kw"])
                    picks.append(row["generator"]["capacity_kw"])
                day += timedelta(days=1)
            entry = {"observed_hours": observed_hours, "hours_without_forecast": without_forecast,
                     "hours_by_method": methods}
            if actual:
                errors = [abs(a - p) for a, p in zip(actual, point)]
                entry.update({
                    "forecast_hours": len(actual),
                    "net_mae_kw": math.fsum(errors) / len(errors),
                    "net_nmae": math.fsum(errors) / math.fsum(abs(a) for a in actual),
                    "upper_coverage": sum(a <= u for a, u in zip(actual, upper)) / len(actual),
                    "generator_changes_per_day": switches / days,
                    "generator_choice": pick_errors(actual, picks, generators, allowed_configurations=allowed)})
            results[f"{scenario}|{'with' if fallbacks else 'without'}_fallback"] = entry
    return results


def summary_markdown(report):
    lines = ["# Missing-input test (Azm, validation month)", "",
             f"Days {report['first_day'][:10]} to {report['last_day'][:10]}, forecast through the served API function. "
             "Weather is not an input, so a missing weather forecast has no effect.", "",
             "| Scenario | Fallback | Hours with no forecast | Net nMAE | Upper coverage | Undersized hours | Oversized hours | Changes per day |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, entry in report["scenarios"].items():
        scenario, fallback = name.split("|")
        if "forecast_hours" not in entry:
            lines.append(f"| {scenario} | {fallback.split('_')[0]} | {entry['hours_without_forecast']} of "
                         f"{entry['observed_hours']} | - | - | - | - | - |")
            continue
        choice = entry["generator_choice"]
        lines.append(f"| {scenario} | {fallback.split('_')[0]} | {entry['hours_without_forecast']} of "
                     f"{entry['observed_hours']} | {entry['net_nmae']:.1%} | {entry['upper_coverage']:.1%} | "
                     f"{choice['undersized_hours']} | {choice['oversized_hours']} | {entry['generator_changes_per_day']:.1f} |")
    lines += ["", "Error and generator columns cover only the hours that received a forecast, so rows "
              "\"without\" fallback look fine on fewer hours: the cost there is the hours with no forecast.", ""]
    return "\n".join(lines)


def main():
    import joblib

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-dir", type=Path, default=Path("outputs/baselines_confirmed_azm"))
    parser.add_argument("--bundle", type=Path, default=Path("outputs/serving/azm_bundle.joblib"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/missing_inputs"))
    args = parser.parse_args()
    _, groups, series, _ = load_inputs(args.baseline_dir)
    bundle = joblib.load(args.bundle)
    group = groups[("azm", "load")]
    first_day = max(datetime.fromisoformat(group["validation_start"]), bundle["training_end_exclusive"])
    end_day = datetime.fromisoformat(group["validation_end_exclusive"])
    report = {"run_time_utc": datetime.now(timezone.utc).isoformat(), "site_id": "azm",
              "first_day": first_day.isoformat(), "last_day": (end_day - timedelta(days=1)).isoformat(),
              "model_sha256": file_sha256(args.bundle), "test_period_scored": False,
              "weather_missing": "no effect: weather is not an input of the served model",
              "scenarios": evaluate(bundle, series[("azm", "load")], series[("azm", "pv")], first_day, end_day)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    (args.output_dir / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
    from . import run_log
    logged = []
    for name, entry in report["scenarios"].items():
        metrics = {"hours_without_forecast": entry["hours_without_forecast"]}
        if "forecast_hours" in entry:
            metrics.update(nmae=entry["net_nmae"], coverage=entry["upper_coverage"],
                           undersized_hours=entry["generator_choice"]["undersized_hours"],
                           oversized_hours=entry["generator_choice"]["oversized_hours"],
                           generator_changes_per_day=entry["generator_changes_per_day"])
        logged += [{"run_time_utc": report["run_time_utc"], "script": "evaluate_missing_inputs", "site_id": "azm",
                    "split": "August (validation)", "method": name, "metric": metric, "value": value,
                    "hours": entry["observed_hours"], "identifier_sha256": report["model_sha256"][:12]}
                   for metric, value in metrics.items()]
    run_log.append(logged)
    print(summary_markdown(report))


if __name__ == "__main__":
    main()

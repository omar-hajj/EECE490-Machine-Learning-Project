"""Describe source variation and failures without changing observations."""

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
from statistics import median


def describe(values):
    ordered = sorted(values)
    return {"hours": len(values), "mean": math.fsum(values) / len(values),
            "median": median(values), "minimum": ordered[0], "maximum": ordered[-1],
            "p95": ordered[int((len(ordered) - 1) * 0.95)],
            "zero_fraction": sum(value == 0 for value in values) / len(values)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--ridge-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".json":
        parser.error("Expected a JSON diagnostic report")
    groups, partitions, months = defaultdict(dict), defaultdict(list), defaultdict(list)
    with (args.baseline_dir / "hourly_data.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = row["site_id"], row["target"]
            timestamp = datetime.fromisoformat(row["timestamp_local_unverified"])
            value = float(row["value_source_units"])
            groups[key][timestamp] = value
            partitions[(*key, row["partition"])].append(value)
            months[(*key, timestamp.strftime("%Y-%m"))].append(value)
    daily_errors = defaultdict(list)
    with (args.ridge_dir / "validation_predictions.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["on_common_comparison_hours"] == "True":
                key = row["site_id"], row["target"], row["timestamp_local_unverified"][:10]
                daily_errors[key].append(abs(float(row["prediction_raw"]) - float(row["actual"])))
    results = []
    for (site, target), series in groups.items():
        runs, run_length, previous, previous_value = [], 0, None, None
        for timestamp, value in sorted(series.items()):
            if previous is not None and timestamp - previous == timedelta(hours=1) and value == previous_value:
                run_length += 1
            else:
                if run_length >= 3:
                    runs.append({"end": previous.isoformat(), "hours": run_length, "value_source_units": previous_value})
                run_length = 1
            previous, previous_value = timestamp, value
        if run_length >= 3:
            runs.append({"end": previous.isoformat(), "hours": run_length, "value_source_units": previous_value})
        days = [{"date": date, "scored_hours": len(errors), "mae_source_units": math.fsum(errors) / len(errors)}
                for (day_site, day_target, date), errors in daily_errors.items() if (day_site, day_target) == (site, target)]
        results.append({"site_id": site, "target": target,
                        "partitions": {partition: describe(values) for (part_site, part_target, partition), values in partitions.items() if (part_site, part_target) == (site, target)},
                        "months": {month: describe(values) for (month_site, month_target, month), values in months.items() if (month_site, month_target) == (site, target)},
                        "constant_runs_at_least_three_hours": runs,
                        "worst_three_ridge_validation_days": sorted(days, key=lambda day: day["mae_source_units"], reverse=True)[:3]})
    report = {"groups": results, "observations_changed": False, "test_months_analyzed": False,
              "interpretation": "Statistics and constant runs are diagnostic flags, not proof of bad sensors. No observations were removed or replaced."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Diagnosed {len(results)} site/channel groups without changing data. Report: {args.output}")


if __name__ == "__main__":
    main()

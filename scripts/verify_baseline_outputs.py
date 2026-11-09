"""Independently reconcile saved baseline CSV files with their JSON results.

Uses only the standard library, without importing the preparation, prediction
or scoring implementation. This checks outputs, not source meter semantics.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import csv
import hashlib
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads((args.output_dir / "results.json").read_text(encoding="utf-8"))
    with args.archive.open("rb") as stream:
        require(hashlib.file_digest(stream, "sha256").hexdigest() == report["source_sha256"], "Source archive hash changed")
    require(not report["test_period_scored"], "The reserved test period must not be scored")
    require(not report["location_only_evaluated"], "This is not a location-only evaluation")
    results = {(group["site_id"], group["target"]): group for group in report["groups"]}
    hourly = defaultdict(dict)
    with (args.output_dir / "hourly_data.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = row["site_id"], row["target"]
            timestamp = datetime.fromisoformat(row["timestamp_local_unverified"])
            end = datetime.fromisoformat(results[key]["validation_end_exclusive"])
            start = datetime.fromisoformat(results[key]["validation_start"])
            require(timestamp < end, "Reserved test observation appears in prepared data")
            require(timestamp not in hourly[key], "Repeated prepared hour")
            require(row["partition"] == ("training" if timestamp < start else "validation"), "Incorrect partition label")
            value_column = "value_source_units" if "value_source_units" in row else "value_source_units_unverified"
            hourly[key][timestamp] = float(row[value_column])
            require(row.get("power_unit", "") == (results[key].get("power_unit") or ""), "Prepared unit differs from site metadata")
    predictions = defaultdict(lambda: defaultdict(dict))
    for key, series in hourly.items():
        profile = defaultdict(list)
        start = datetime.fromisoformat(results[key]["validation_start"])
        for timestamp, value in series.items():
            if timestamp < start:
                profile[(timestamp.weekday(), timestamp.hour)].append(value)
        # Reconstruct from saved prepared values; do not call the model code.
        predictions[key]["training_profile"] = {slot: math.fsum(values) / len(values) for slot, values in profile.items()}
    with (args.output_dir / "validation_predictions.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = row["site_id"], row["target"]
            group = results[key]
            require(row.get("power_unit", "") == (group.get("power_unit") or ""), "Prediction unit differs from site metadata")
            timestamp = datetime.fromisoformat(row["timestamp_local_unverified"])
            issue_time = datetime.fromisoformat(row["issue_time_local_unverified"])
            start = datetime.fromisoformat(group["validation_start"])
            end = datetime.fromisoformat(group["validation_end_exclusive"])
            require(start <= timestamp < end, "Prediction falls outside validation")
            require(issue_time == timestamp.replace(hour=0), "Wrong forecast issue time")
            actual = float(row["actual"]) if row["actual"] else None
            prediction = float(row["prediction"]) if row["prediction"] else None
            require(actual == hourly[key].get(timestamp), "Scored actual differs from prepared data")
            method = row["method"]
            require(timestamp not in predictions[key][method], "Repeated prediction key")
            if method in {"yesterday", "last_week"}:
                expected = hourly[key].get(timestamp - timedelta(days=1 if method == "yesterday" else 7))
            elif method == "weekday_average":
                expected = predictions[key]["training_profile"].get((timestamp.weekday(), timestamp.hour))
            else:
                raise ValueError("Unknown saved method")
            require((prediction is None and expected is None) or (
                prediction is not None and expected is not None and math.isclose(prediction, expected, rel_tol=1e-12, abs_tol=1e-12)
            ), "Prediction cannot be reproduced from available history")
            scored = actual is not None and prediction is not None
            require((row["scored"] == "True") == scored, "Incorrect scored flag")
            if prediction is not None:
                require(datetime.fromisoformat(row["latest_input_available_at_local_unverified"]) <= issue_time,
                        "Prediction uses data unavailable at midnight")
            predictions[key][method][timestamp] = (actual, prediction)
    verified_groups = 0
    for key, group in results.items():
        methods = group["methods"]
        available = {}
        for method in methods:
            saved = predictions[key][method]
            require(len(saved) == group["calendar_hours"], "Missing calendar-hour prediction rows")
            available[method] = {stamp for stamp, (actual, prediction) in saved.items() if actual is not None and prediction is not None}
            require(len(available[method]) == methods[method]["scored_hours"], "Individual coverage differs")
        common = set.intersection(*available.values())
        require(len(common) == group["common_scored_hours"], "Common coverage differs")
        for method, result in methods.items():
            scores = result["common_hours_scores"]
            if not common:
                require(scores is None, "Empty comparison should have no score")
                continue
            pairs = [predictions[key][method][timestamp] for timestamp in sorted(common)]
            errors = [abs(prediction - actual) for actual, prediction in pairs]
            mean_actual = math.fsum(actual for actual, _ in pairs) / len(pairs)
            mae = math.fsum(errors) / len(errors)
            rmse = math.sqrt(math.fsum(error * error for error in errors) / len(errors))
            for field, value in (("mae", mae), ("rmse", rmse), ("maximum_absolute_error", max(errors)), ("mean_actual", mean_actual)):
                require(math.isclose(scores[field], value, rel_tol=1e-12, abs_tol=1e-12), f"Incorrect {field}")
            if mean_actual:
                require(math.isclose(scores["nmae"], mae / mean_actual, rel_tol=1e-12, abs_tol=1e-12), "Incorrect nMAE")
            else:
                require(scores["nmae"] is None, "Zero denominator should have undefined nMAE")
        verified_groups += 1
    print(f"Verified {verified_groups} site/channel groups: predictions, coverage, errors, issue times, test exclusion and unchanged source hash.")


if __name__ == "__main__":
    main()

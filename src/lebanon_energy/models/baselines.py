"""Midnight-issued baselines and the approved baseline run (preparation is in data/preparation.py).

All values retain their original source units; confirmed units are recorded
per site. Source clock conventions and meter boundaries remain unverified.
No geographic or equipment inference is performed. The reserved test period
is excluded before aggregation.
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import warnings
from zipfile import ZipFile

from ..data.preparation import _site_records, file_sha256, hourly_means, mask_frozen_readings, source_path
from ..evaluation.metrics import score


METHODS = ("yesterday", "last_week", "weekday_average")


def fit_weekday_profile(series, training_end):
    groups = defaultdict(list)
    for timestamp, value in series.items():
        if timestamp < training_end:
            groups[(timestamp.weekday(), timestamp.hour)].append((timestamp, value))
    return {key: (math.fsum(value for _, value in rows) / len(rows),
                  max(timestamp for timestamp, _ in rows) + timedelta(hours=1))
            for key, rows in groups.items()}


def predict(series, profile, timestamp, method):
    """Return prediction and latest availability time; never use same-day data."""
    issue_time = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    if method == "weekday_average":
        result = profile.get((timestamp.weekday(), timestamp.hour))
    elif method in ("yesterday", "last_week"):
        source_hour = timestamp - timedelta(hours=24 if method == "yesterday" else 168)
        value = series.get(source_hour)
        result = None if value is None else (value, source_hour + timedelta(hours=1))
    else:
        raise ValueError(f"Unknown method: {method}")
    if result is not None and result[1] > issue_time:
        raise ValueError("Prediction input would become available after the midnight issue time")
    return result


def evaluate_series(series, *, start, end):
    if end <= start or any((point.hour, point.minute, point.second, point.microsecond) != (0, 0, 0, 0) for point in (start, end)):
        raise ValueError("Validation must have increasing midnight boundaries")
    profile = fit_weekday_profile(series, start)
    rows, timestamp = [], start
    while timestamp < end:
        actual = series.get(timestamp)
        predictions, availability = {}, {}
        for method in METHODS:
            result = predict(series, profile, timestamp, method)
            predictions[method] = result[0] if result else None
            availability[method] = result[1].isoformat() if result else None
        rows.append({"timestamp": timestamp.isoformat(),
                     "issue_time": timestamp.replace(hour=0).isoformat(),
                     "actual": actual, "predictions": predictions,
                     "latest_input_available_at": availability})
        timestamp += timedelta(hours=1)
    observed = [row for row in rows if row["actual"] is not None]
    common = [row for row in observed if all(value is not None for value in row["predictions"].values())]
    methods = {}
    for method in METHODS:
        own = [row for row in observed if row["predictions"][method] is not None]
        methods[method] = {
            "predictions_available_hours": sum(row["predictions"][method] is not None for row in rows),
            "scored_hours": len(own),
            "scored_fraction_of_observed": len(own) / len(observed) if observed else None,
            "own_available_hours_scores": asdict(score(
                [row["actual"] for row in own], [row["predictions"][method] for row in own])) if own else None,
            "common_hours_scores": asdict(score(
                [row["actual"] for row in common], [row["predictions"][method] for row in common])) if common else None,
        }
    defined = {name: result["common_hours_scores"]["nmae"] for name, result in methods.items()
               if result["common_hours_scores"] and result["common_hours_scores"]["nmae"] is not None}
    lowest = min(defined.values()) if defined else None
    summary = {
        "validation_start": start.isoformat(), "validation_end_exclusive": end.isoformat(),
        "calendar_hours": len(rows), "observed_complete_hours": len(observed),
        "missing_actual_hours": len(rows) - len(observed),
        "common_scored_hours": len(common),
        "common_fraction_of_calendar_hours": len(common) / len(rows),
        "lowest_common_validation_nmae_methods": [name for name, value in defined.items() if value == lowest],
        "methods": methods,
    }
    return summary, rows


def run_experiment(archive_path, configuration, sites):
    if configuration.get("approval_status") != "approved_by_user":
        raise ValueError("The baseline preparation protocol needs user approval")
    report = {
        "status": "provisional_history_based_validation_only",
        "run_time_utc": datetime.now(timezone.utc).isoformat(),
        "source_archive": Path(archive_path).name, "source_sha256": file_sha256(archive_path),
        "protocol": configuration, "groups": [], "preparation": [],
        "site_measurement_metadata": [
            {"site_id": site["site_id"], "power_unit": site.get("power_unit_confirmed"),
             "confirmed_source_meanings": site.get("confirmed_source_meanings", {}),
             "confirmation_source": site.get("metadata_confirmation_source")}
            for site in sites
        ],
        "test_period_scored": False, "location_only_evaluated": False,
        "warnings": [
            "Source clock conventions and meter boundaries remain unverified; units are confirmed only where recorded in site metadata.",
            "Recorded zeros, spikes and frozen values were not automatically removed.",
            "Household 1/2 February and March 2025 duplicate each other; site scores are not independent.",
            "No national aggregate, generator recommendation or location-only accuracy is inferred.",
        ],
    }
    all_hourly, all_predictions = [], []
    with ZipFile(archive_path) as archive:
        for site in sites:
            site_id = site["site_id"]
            profile = configuration["azm" if site_id == "azm" else "other_sites"]
            start = datetime.fromisoformat(profile["validation_start"])
            end = datetime.fromisoformat(profile["validation_end_exclusive"])
            counters = {"timestamp_interpretations": Counter(), "positive_intervals_seconds": Counter(),
                        "reserved_or_later_rows_not_used": 0,
                        "workbooks_read": 0, "reserved_workbooks_not_opened": []}
            records = _site_records(archive, site, profile, counters)
            frozen_rule = configuration.get("frozen_readings")
            frozen_stretches = None
            if frozen_rule and site_id in frozen_rule["site_ids"]:
                records, frozen_stretches = mask_frozen_readings(
                    records, targets=profile["targets"], sampling_minutes=profile["sampling_minutes"],
                    minimum_consecutive_readings=frozen_rule["minimum_consecutive_readings"])
            hourly, preparation = hourly_means(records, targets=profile["targets"],
                                               sampling_minutes=profile["sampling_minutes"], cutoff=end)
            if frozen_stretches is not None:
                preparation["frozen_stretches_masked"] = frozen_stretches
            intervals = counters["positive_intervals_seconds"]
            if not intervals or intervals.most_common(1)[0][0] != profile["sampling_minutes"] * 60:
                raise ValueError(f"Observed modal cadence does not match the approved protocol for {site_id}")
            preparation.update({"site_id": site_id, "source_label": site["source_label"],
                                "workbooks_read": counters["workbooks_read"],
                                "reserved_workbooks_not_opened": counters["reserved_workbooks_not_opened"],
                                "reserved_or_later_rows_not_used": counters["reserved_or_later_rows_not_used"],
                                "modal_interval_seconds": intervals.most_common(1)[0][0],
                                "timestamp_interpretations": dict(counters["timestamp_interpretations"])})
            report["preparation"].append(preparation)
            for target, series in hourly.items():
                summary, predictions = evaluate_series(series, start=start, end=end)
                report["groups"].append({"site_id": site_id, "target": target,
                                         "power_unit": site.get("power_unit_confirmed"),
                                         "confirmed_source_meaning": site.get("confirmed_source_meanings", {}).get(profile["targets"][target]),
                                         "source_column": profile["targets"][target], **summary})
                for timestamp, value in sorted(series.items()):
                    all_hourly.append({"site_id": site_id, "timestamp_local_unverified": timestamp.isoformat(),
                                       "target": target, "source_column": profile["targets"][target],
                                       "value_source_units": value,
                                       "power_unit": site.get("power_unit_confirmed"),
                                       "partition": "training" if timestamp < start else "validation"})
                for row in predictions:
                    for method in METHODS:
                        predicted = row["predictions"][method]
                        reason = []
                        if row["actual"] is None:
                            reason.append("actual_hour_incomplete_or_absent")
                        if predicted is None:
                            reason.append("required_history_unavailable")
                        all_predictions.append({"site_id": site_id, "target": target,
                                                "power_unit": site.get("power_unit_confirmed"),
                                                "timestamp_local_unverified": row["timestamp"],
                                                "issue_time_local_unverified": row["issue_time"],
                                                "method": method, "actual": row["actual"], "prediction": predicted,
                                                "latest_input_available_at_local_unverified": row["latest_input_available_at"][method],
                                                "scored": not reason, "not_scored_reason": ";".join(reason)})
            print(f"Prepared and evaluated {site_id} ({preparation['included_raw_records']} source records).", flush=True)
    report["source_unchanged"] = file_sha256(archive_path) == report["source_sha256"]
    if not report["source_unchanged"]:
        raise RuntimeError("Source archive changed during this experiment")
    return report, all_hourly, all_predictions


def _summary_markdown(report):
    lines = ["# First history-based baseline results", "",
             "Provisional validation results. The final test months were not scored.", "",
             "Errors below use the same observed hours for all three methods within each site/target.",
             "nMAE = average absolute error divided by average actual value; lower is better.",
             "These percentages are not MAPE or a percentage accuracy score.", "",
             "| Site | Channel | Common hours / calendar hours | Yesterday nMAE | Last week nMAE | Weekday average nMAE | Lowest measured nMAE |",
             "| --- | --- | ---: | ---: | ---: | ---: | --- |"]
    for group in report["groups"]:
        values = []
        for method in METHODS:
            scores = group["methods"][method]["common_hours_scores"]
            values.append(f"{scores['nmae']:.1%}" if scores and scores["nmae"] is not None else "undefined")
        best = ", ".join(group["lowest_common_validation_nmae_methods"]) or "undefined"
        channel = group['source_column'] + (f" ({group['power_unit']})" if group['power_unit'] else " (unit unconfirmed)")
        lines.append(f"| {group['site_id']} | {channel} | {group['common_scored_hours']} / {group['calendar_hours']} | {' | '.join(values)} | {best} |")
    lines.extend(["", "## Interpretation limits", ""] + ["- " + warning for warning in report["warnings"]])
    lines.extend(["", "The full JSON contains MAE, RMSE, maximum absolute errors, individual-method",
                  "coverage and exclusion counts. Raw errors retain each source's original units.",
                  "The CSV files contain prepared hours and every validation prediction, including",
                  "explicit missing predictions. No missing input was filled.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--sites", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    configuration = json.loads(args.config.read_text(encoding="utf-8"))
    sites = json.loads(args.sites.read_text(encoding="utf-8"))["sites"]
    report, hourly, predictions = run_experiment(args.archive, configuration, sites)
    report["code_sha256"] = {path.name: file_sha256(path) for path in (
        Path(__file__), source_path("data.preparation"), source_path("data.audit"), source_path("evaluation.metrics"))}
    report["site_configuration_sha256"] = file_sha256(args.sites)
    report["baseline_configuration_sha256"] = file_sha256(args.config)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    (args.output_dir / "summary.md").write_text(_summary_markdown(report), encoding="utf-8")
    for name, records in (("hourly_data.csv", hourly), ("validation_predictions.csv", predictions)):
        if not records:
            raise ValueError(f"No records generated for {name}")
        with (args.output_dir / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    print(f"Results saved to {args.output_dir}")


if __name__ == "__main__":
    main()

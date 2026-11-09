"""Recompute comparisons on identical hours across all available model runs."""

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from lebanon_energy.baselines import METHODS, file_sha256
from lebanon_energy.evaluation import score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--runs", required=True, nargs="+", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    reference = json.loads((args.baseline_dir / "results.json").read_text())
    if reference["test_period_scored"]:
        raise ValueError("Only validation experiments can be compared here")
    groups = {(group["site_id"], group["target"]): group for group in reference["groups"]}
    actuals, predictions, run_metadata = defaultdict(dict), defaultdict(lambda: defaultdict(dict)), {}
    with (args.baseline_dir / "validation_predictions.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = row["site_id"], row["target"]
            timestamp = row["timestamp_local_unverified"]
            observed = float(row["actual"]) if row["actual"] else None
            if timestamp in actuals[key] and actuals[key][timestamp] != observed:
                raise ValueError("Inconsistent actuals between baseline rows")
            actuals[key][timestamp] = observed
            predictions[key][row["method"]][timestamp] = float(row["prediction"]) if row["prediction"] else None
    for directory in args.runs:
        name = directory.name
        if name in run_metadata or name in METHODS:
            raise ValueError("Model run names must be unique")
        report = json.loads((directory / "results.json").read_text())
        if report["test_period_scored"] or report["source_sha256"] != reference["source_sha256"]:
            raise ValueError("Model source/split differs from validation baseline")
        run_metadata[name] = {"model": report.get("model", "Ridge"), "weather_used": report["weather_used"],
                              "results_sha256": file_sha256(directory / "results.json"),
                              "predictions_sha256": file_sha256(directory / "validation_predictions.csv")}
        for group in report["groups"]:
            if group["status"] == "validation_tuned_not_final_tested":
                predictions[(group["site_id"], group["target"])][name] = {}
        with (directory / "validation_predictions.csv").open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                key, timestamp = (row["site_id"], row["target"]), row["timestamp_local_unverified"]
                if key not in groups or timestamp not in actuals[key]:
                    raise ValueError("Model row outside the baseline validation grid")
                observed = float(row["actual"]) if row["actual"] else None
                if observed != actuals[key][timestamp] or timestamp in predictions[key][name]:
                    raise ValueError("Mismatched actual or duplicate prediction")
                predictions[key][name][timestamp] = float(row["prediction_raw"]) if row["prediction_raw"] else None
    results = []
    for key, group in groups.items():
        for timestamp in actuals[key]:
            if not group["validation_start"] <= timestamp < group["validation_end_exclusive"]:
                raise ValueError("Non-validation observation")
        methods = predictions[key]
        common = [timestamp for timestamp, value in actuals[key].items() if value is not None and
                  all(method.get(timestamp) is not None for method in methods.values())]
        if not common:
            raise ValueError("No shared validation observations")
        scores = {name: asdict(score([actuals[key][timestamp] for timestamp in common],
                                    [values[timestamp] for timestamp in common])) for name, values in methods.items()}
        best_baseline = min(METHODS, key=lambda method: scores[method]["mae"])
        lowest = min(value["mae"] for value in scores.values())
        results.append({"site_id": key[0], "target": key[1], "power_unit": group.get("power_unit"),
                        "calendar_hours": len(actuals[key]), "common_hours": len(common),
                        "observed_hours": sum(value is not None for value in actuals[key].values()),
                        "best_baseline": best_baseline, "scores": scores,
                        "lowest_validation_mae_methods": [name for name, value in scores.items() if value["mae"] == lowest]})
    report = {"source_sha256": reference["source_sha256"], "runs": run_metadata, "groups": results,
              "test_period_scored": False, "deployment_model_selected": False,
              "metric": "nMAE = mean absolute error / mean actual; not MAPE or percentage accuracy",
              "limitations": ["Parameters tuned on validation; final-test accuracy remains unknown.",
                              "Weather comparisons are preliminary; actual publication timing unverified.",
                              "All models use site history; no location-only result is inferred.",
                              "No raw-data corrections, equipment capacities, reserve margin or deployment choice inferred."]}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    names = list(run_metadata)
    lines = ["# Validation model comparison", "", report["metric"], "Lower is better. All columns in each row use identical observed hours.", "",
             "| Site | Target | Shared hours | Best simple baseline | " + " | ".join(names) + " |",
             "| --- | --- | ---: | ---: | " + " | ".join("---:" for _ in names) + " |"]
    for group in results:
        def show(name):
            value = group["scores"].get(name, {}).get("nmae")
            return f"{value:.1%}" if value is not None else "—"
        lines.append(f"| {group['site_id']} | {group['target']} | {group['common_hours']} | {show(group['best_baseline'])} | " + " | ".join(show(name) for name in names) + " |")
    lines.extend(["", "## Limits", ""] + ["- " + value for value in report["limitations"]])
    (args.output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Compared {len(results)} site/target groups across {len(names)} model runs on shared hours.")


if __name__ == "__main__":
    main()

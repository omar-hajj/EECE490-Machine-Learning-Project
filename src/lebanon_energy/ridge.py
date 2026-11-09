"""Train per-site Ridge forecasts and compare on shared validation hours.

Uses approved prepared data only. No future observed weather, target-site
transfer claim, test labels, automatic source correction or production model
selection is introduced by this experiment.
"""

import argparse
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import csv
import importlib.metadata
import json
import math
from pathlib import Path
import re

from .baselines import METHODS, file_sha256
from .evaluation import score
from .features import history_calendar_features


def load_inputs(directory):
    directory = Path(directory)
    report = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    if report.get("test_period_scored") or not report.get("source_unchanged"):
        raise ValueError("Expected verified validation-only baseline inputs")
    groups = {(group["site_id"], group["target"]): group for group in report["groups"]}
    series = defaultdict(dict)
    with (directory / "hourly_data.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = row["site_id"], row["target"]
            if key not in groups or not re.fullmatch(r"[a-z0-9_]+", key[0]) or key[1] not in {"load", "pv"}:
                raise ValueError("Unexpected site/target identifier in prepared inputs")
            group = groups[key]
            timestamp = datetime.fromisoformat(row["timestamp_local_unverified"])
            if timestamp.tzinfo is not None or timestamp >= datetime.fromisoformat(group["validation_end_exclusive"]):
                raise ValueError("Prepared input contains an unexpected clock or reserved test hour")
            expected_partition = "training" if timestamp < datetime.fromisoformat(group["validation_start"]) else "validation"
            if row["partition"] != expected_partition or timestamp in series[key]:
                raise ValueError("Unexpected partition or repeated prepared timestamp")
            value = float(row["value_source_units"])
            if not math.isfinite(value) or value < 0:
                raise ValueError("Prepared source values must be finite and nonnegative")
            series[key][timestamp] = value
    baseline_predictions = defaultdict(lambda: defaultdict(dict))
    with (directory / "validation_predictions.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            key = row["site_id"], row["target"]
            if key not in groups or row["method"] not in METHODS:
                raise ValueError("Unexpected baseline prediction group")
            timestamp = datetime.fromisoformat(row["timestamp_local_unverified"])
            actual = float(row["actual"]) if row["actual"] else None
            if actual != series[key].get(timestamp):
                raise ValueError("Baseline actual differs from the prepared target")
            if row["method"] in baseline_predictions[key][timestamp]:
                raise ValueError("Duplicate baseline prediction key")
            value = float(row["prediction"]) if row["prediction"] else None
            baseline_predictions[key][timestamp][row["method"]] = value
    return report, groups, series, baseline_predictions


def model_features(series, timestamp, lag_hours, weather=None):
    features, available_at = history_calendar_features(series, timestamp, lag_hours)
    if features is None or weather is None:
        return features, available_at
    entry = weather.get(timestamp)
    if entry is None:
        return None, None
    if entry["available_at"] > timestamp.replace(hour=0):
        raise ValueError("Nominal weather availability is after the midnight forecast issue time")
    features.update(entry["features"])
    return features, max(available_at, entry["available_at"])


def build_rows(series, start, end, lag_hours, weather=None):
    training, validation = [], []
    for timestamp, actual in sorted(series.items()):
        if timestamp >= start:
            continue
        features, available_at = model_features(series, timestamp, lag_hours, weather)
        if features is not None:
            training.append({"timestamp": timestamp, "actual": actual, "features": features,
                             "available_at": available_at})
    timestamp = start
    while timestamp < end:
        features, available_at = model_features(series, timestamp, lag_hours, weather)
        validation.append({"timestamp": timestamp, "actual": series.get(timestamp),
                           "features": features, "available_at": available_at})
        timestamp += timedelta(hours=1)
    return training, validation


def make_pipeline(alpha):
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline([
        ("vectorizer", DictVectorizer(sparse=False)),
        ("scaler", StandardScaler()),
        ("ridge", Ridge(alpha=alpha, solver="cholesky")),
    ])


def _scores(rows, predictions):
    return asdict(score([row["actual"] for row in rows], [float(value) for value in predictions]))


def train_group(series, group, baselines, configuration, weather=None, pipeline_factory=None):
    import numpy as np

    start = datetime.fromisoformat(group["validation_start"])
    end = datetime.fromisoformat(group["validation_end_exclusive"])
    training, validation = build_rows(series, start, end, tuple(configuration["lag_hours"]), weather)
    predictable = [row for row in validation if row["features"] is not None]
    common = [row for row in predictable if row["actual"] is not None and
              all(baselines.get(row["timestamp"], {}).get(method) is not None for method in METHODS)]
    if len(training) < 2 or not common:
        return {"status": "insufficient_training_or_shared_validation_hours",
                "training_rows": len(training), "common_hours": len(common)}, None, []
    x_train = [row["features"] for row in training]
    y_train = [row["actual"] for row in training]
    x_common = [row["features"] for row in common]
    candidates, best_model, best_score = [], None, None
    parameters_to_try = configuration.get("candidate_parameters") or [{"alpha": alpha} for alpha in configuration["alpha_candidates"]]
    factory = pipeline_factory or make_pipeline
    for parameters in parameters_to_try:
        alpha = parameters.get("alpha")
        if alpha is not None and (not math.isfinite(alpha) or alpha <= 0):
            raise ValueError("Ridge alpha candidates must be finite and positive")
        model = factory(**parameters)
        model.fit(x_train, y_train)
        predicted = model.predict(x_common)
        measured = _scores(common, predicted)
        candidates.append({"alpha": alpha, "parameters": parameters, "common_validation_scores_raw": measured})
        if best_score is None or measured["mae"] < best_score["mae"]:
            best_model, best_score = model, measured
            best_parameters = parameters
    predicted_common = best_model.predict(x_common)
    clipped_common = np.maximum(predicted_common, 0)
    baseline_scores = {method: asdict(score(
        [row["actual"] for row in common], [baselines[row["timestamp"]][method] for row in common])) for method in METHODS}
    best_baseline_mae = min(scores["mae"] for scores in baseline_scores.values())
    best_baselines = [method for method, scores in baseline_scores.items() if scores["mae"] == best_baseline_mae]
    forecast_values = iter(best_model.predict([row["features"] for row in predictable]))
    saved_rows = []
    for row in validation:
        predicted = float(next(forecast_values)) if row["features"] is not None else None
        available_at = row["available_at"]
        saved_rows.append({"timestamp_local_unverified": row["timestamp"].isoformat(),
                           "issue_time_local_unverified": row["timestamp"].replace(hour=0).isoformat(),
                           "actual": row["actual"], "prediction_raw": predicted,
                           "prediction_clipped_diagnostic": max(0, predicted) if predicted is not None else None,
                           "latest_input_available_at_local_unverified": available_at.isoformat() if available_at else None,
                           "scored": row["actual"] is not None and predicted is not None,
                           "on_common_comparison_hours": row in common,
                           "missing_reason": "required_history_or_weather_absent" if row["features"] is None else (
                               "actual_hour_incomplete_or_absent" if row["actual"] is None else "")})
    own = [row for row in saved_rows if row["scored"]]
    result = {
        "status": "validation_tuned_not_final_tested", "selected_alpha": best_parameters.get("alpha"),
        "selected_parameters": best_parameters,
        "training_rows": len(training), "training_start": training[0]["timestamp"].isoformat(),
        "training_last_target": training[-1]["timestamp"].isoformat(),
        "training_latest_input_available_at": max(row["available_at"] for row in training).isoformat(),
        "calendar_validation_hours": len(validation), "observed_validation_hours": sum(row["actual"] is not None for row in validation),
        "prediction_available_hours": len(predictable), "own_scored_hours": len(own), "common_comparison_hours": len(common),
        "alpha_search": candidates, "ridge_common_scores_raw": best_score,
        "ridge_common_scores_clipped_diagnostic": _scores(common, clipped_common),
        "ridge_own_available_scores_raw": asdict(score([row["actual"] for row in own], [row["prediction_raw"] for row in own])),
        "baseline_common_scores": baseline_scores, "best_baseline_methods": best_baselines,
        "relative_mae_improvement_over_best_baseline": (best_baseline_mae - best_score["mae"]) / best_baseline_mae if best_baseline_mae else None,
        "negative_predictions_on_common_hours": int(sum(value < 0 for value in predicted_common)),
        "deployment_model_selected": False,
    }
    return result, best_model, saved_rows


def _write_summary(report):
    mode_description = ("Preliminary weather-assisted results using nominal day-ahead timing; publication availability is unverified."
                        if report["weather_used"] else "History and calendar inputs only. Weather is pending alignment verification.")
    lines = ["# Ridge validation results", "", mode_description,
             "Hyperparameters were tuned on validation; these are development results, not final-test estimates.",
             "Each row compares Ridge with all three baselines on identical observed hours.", "",
             "| Site | Target | Unit | Shared hours | Best baseline nMAE | Ridge nMAE | Relative MAE improvement |",
             "| --- | --- | --- | ---: | ---: | ---: | ---: |"]
    for group in report["groups"]:
        if group["status"] != "validation_tuned_not_final_tested":
            continue
        baseline = min(group["baseline_common_scores"].values(), key=lambda scores: scores["mae"])
        ridge = group["ridge_common_scores_raw"]
        ratio = group["relative_mae_improvement_over_best_baseline"]
        as_percent = lambda value: f"{value:.1%}" if value is not None else "undefined"
        lines.append(f"| {group['site_id']} | {group['target']} | {group['power_unit'] or 'unconfirmed'} | {group['common_comparison_hours']} | {as_percent(baseline['nmae'])} | {as_percent(ridge['nmae'])} | {as_percent(ratio)} |")
    lines.extend(["", "Positive improvement means Ridge has lower error; negative means the best baseline has lower error.",
                  "nMAE is MAE divided by mean actual; it is not MAPE or a percentage accuracy.", "",
                  "## Limits", ""] + ["- " + warning for warning in report["warnings"]])
    return "\n".join(lines) + "\n"


def load_weather(path, groups):
    from .weather import VARIABLES

    metadata = json.loads(path.with_name("metadata.json").read_text())
    if not metadata["clock_confirmed_by_user"] or metadata["meter_clock"] != "Asia/Beirut":
        raise ValueError("Weather requires a confirmed meter clock")
    weather = defaultdict(dict)
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            site_id = row["site_id"]
            matching = [group for (site, _), group in groups.items() if site == site_id]
            if not matching:
                raise ValueError("Unknown weather site")
            timestamp = datetime.fromisoformat(row["timestamp_local"])
            cutoff = datetime.fromisoformat(matching[0]["validation_end_exclusive"])
            if timestamp.tzinfo is not None or timestamp >= cutoff or timestamp in weather[site_id]:
                raise ValueError("Unexpected clock, reserved-test weather hour or duplicate weather key")
            features = {name: float(row[name]) for name in VARIABLES}
            if not all(math.isfinite(value) for value in features.values()):
                raise ValueError("Weather features must be finite")
            weather[site_id][timestamp] = {"features": features,
                                          "available_at": datetime.fromisoformat(row["nominal_available_at_local"])}
    return weather, metadata


def main():
    import joblib
    from threadpoolctl import threadpool_limits

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--weather-features", type=Path)
    args = parser.parse_args()
    configuration = json.loads(args.config.read_text(encoding="utf-8"))
    baseline_report, groups, series, baselines = load_inputs(args.baseline_dir)
    if file_sha256(args.archive) != baseline_report["source_sha256"]:
        raise ValueError("Source archive differs from the verified baseline source")
    weather, weather_metadata = None, None
    if configuration["weather"]["enabled"]:
        if not configuration["weather"].get("provisional_nominal_availability_approved_by_user") or args.weather_features is None:
            raise ValueError("The preliminary weather experiment requires explicit approval and aligned weather inputs")
        weather, weather_metadata = load_weather(args.weather_features, groups)
        if weather_metadata["source_sha256"] != baseline_report["source_sha256"]:
            raise ValueError("Weather was prepared from another source archive")
        if not configuration.get("site_ids") or any(site not in weather for site in configuration["site_ids"]):
            raise ValueError("Weather experiment needs an explicit set of sites with weather")
    elif args.weather_features is not None:
        raise ValueError("Weather input supplied to a history-only experiment")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_directory = args.output_dir / "models"
    model_directory.mkdir(exist_ok=True)
    report = {
        "run_time_utc": datetime.now(timezone.utc).isoformat(), "configuration": configuration,
        "source_sha256": baseline_report["source_sha256"], "groups": [],
        "versions": {name: importlib.metadata.version(name) for name in ("scikit-learn", "numpy", "scipy", "joblib", "tzdata")},
        "input_sha256": {name: file_sha256(args.baseline_dir / name) for name in ("results.json", "hourly_data.csv", "validation_predictions.csv")},
        "configuration_sha256": file_sha256(args.config),
        "code_sha256": {path.name: file_sha256(path) for path in (
            Path(__file__), Path(__file__).with_name("features.py"), Path(__file__).with_name("evaluation.py"))},
        "test_period_scored": False, "weather_used": weather is not None, "location_only_evaluated": False,
        "warnings": [
            "Validation was used to tune alpha; improvements require confirmation on the untouched final test.",
            ("Preliminary weather experiment approved by the user: nominal 24-hour forecast lead is used; actual publication times remain unverified."
             if weather is not None else "Weather was excluded pending clock/provenance/interval alignment; the saved run is history/calendar only."),
            "Azm's clock is confirmed as Lebanese local time; zero meter transmission delay and other sites' clocks remain unverified.",
            "Azm units are kW; other sites' units remain unconfirmed. Recorded spikes and frozen values were retained.",
            "Household 1/2 share duplicated historical months; site results are not independent transfer evidence.",
            "Raw Ridge predictions may be negative. Nonnegative clipping is reported separately as a diagnostic, not silently applied.",
            "No production model or generator policy has been selected; no location-only comparison has been made.",
        ],
    }
    if weather is not None:
        report["weather_alignment_metadata"] = weather_metadata
        report["weather_input_sha256"] = {"features.csv": file_sha256(args.weather_features),
                                          "metadata.json": file_sha256(args.weather_features.with_name("metadata.json"))}
        report["code_sha256"]["weather.py"] = file_sha256(Path(__file__).with_name("weather.py"))
    all_rows = []
    with threadpool_limits(limits=1):
        for key, group in groups.items():
            if configuration.get("site_ids") and key[0] not in configuration["site_ids"]:
                continue
            result, model, predictions = train_group(series[key], group, baselines[key], configuration,
                                                      weather[key[0]] if weather is not None else None)
            result.update({"site_id": key[0], "target": key[1], "power_unit": group.get("power_unit"),
                           "validation_start": group["validation_start"], "validation_end_exclusive": group["validation_end_exclusive"]})
            if model is not None:
                model_file = model_directory / f"{key[0]}_{key[1]}.joblib"
                joblib.dump(model, model_file)
                result["model_file"] = str(model_file.relative_to(args.output_dir))
                result["model_sha256"] = file_sha256(model_file)
            report["groups"].append(result)
            for row in predictions:
                all_rows.append({"site_id": key[0], "target": key[1], "power_unit": group.get("power_unit"), **row})
            print(f"Trained {key[0]} {key[1]}: {result['status']}", flush=True)
    report["source_unchanged"] = file_sha256(args.archive) == report["source_sha256"]
    if not report["source_unchanged"]:
        raise ValueError("Source archive changed during modeling")
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    (args.output_dir / "summary.md").write_text(_write_summary(report), encoding="utf-8")
    with (args.output_dir / "validation_predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"Saved Ridge results and models to {args.output_dir}")


if __name__ == "__main__":
    main()

"""XGBoost comparison using the established features and paired scoring."""

import argparse
import csv
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path

from .baselines import file_sha256
from .ridge import load_inputs, load_weather, train_group


def make_pipeline(**parameters):
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.pipeline import Pipeline
    from xgboost import XGBRegressor

    return Pipeline([
        ("vectorizer", DictVectorizer(sparse=False)),
        ("boosting", XGBRegressor(objective="reg:squarederror", tree_method="hist",
                                  n_jobs=1, random_state=42, min_child_weight=5,
                                  reg_lambda=1, **parameters)),
    ])


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
    configuration = json.loads(args.config.read_text())
    baseline_report, groups, series, baselines = load_inputs(args.baseline_dir)
    if file_sha256(args.archive) != baseline_report["source_sha256"]:
        raise ValueError("Source archive differs from verified baseline input")
    weather, weather_metadata = None, None
    if configuration["weather"]["enabled"]:
        if not configuration["weather"].get("provisional_nominal_availability_approved_by_user") or args.weather_features is None:
            raise ValueError("Weather requires explicit provisional approval and aligned inputs")
        weather, weather_metadata = load_weather(args.weather_features, groups)
        if weather_metadata["source_sha256"] != baseline_report["source_sha256"]:
            raise ValueError("Weather source differs")
        if not configuration.get("site_ids") or any(site not in weather for site in configuration["site_ids"]):
            raise ValueError("Specify only sites with supplied weather")
    elif args.weather_features is not None:
        raise ValueError("Weather supplied to a history-only run")
    report = {
        "model": "XGBoost", "run_time_utc": datetime.now(timezone.utc).isoformat(),
        "configuration": configuration, "source_sha256": baseline_report["source_sha256"],
        "input_sha256": {name: file_sha256(args.baseline_dir / name) for name in ("results.json", "hourly_data.csv", "validation_predictions.csv")},
        "code_sha256": {path.name: file_sha256(path) for path in (Path(__file__), Path(__file__).with_name("ridge.py"), Path(__file__).with_name("features.py"), Path(__file__).with_name("evaluation.py"))},
        "configuration_sha256": file_sha256(args.config),
        "versions": {name: importlib.metadata.version(name) for name in ("xgboost", "scikit-learn", "numpy", "joblib")},
        "weather_used": weather is not None, "test_period_scored": False,
        "location_only_evaluated": False, "deployment_model_selected": False, "groups": [],
        "warnings": ["Hyperparameters selected on validation; final-test performance is unknown.",
                     "Source units remain unconfirmed outside Azm; original zeros, spikes and constant runs retained.",
                     "Independent site models are not a location-only or national generalization experiment.",
                     "Raw predictions and clipping diagnostics are separate. No deployment model selected."]}
    if weather is not None:
        report["weather_alignment_metadata"] = weather_metadata
        report["weather_input_sha256"] = {name: file_sha256(args.weather_features.with_name(name)) for name in ("features.csv", "metadata.json")}
        report["warnings"].append("User-approved preliminary weather timing uses nominal previous_day1 lead; publication times unverified.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "models").mkdir(exist_ok=True)
    saved_rows = []
    rename = {"ridge_common_scores_raw": "xgboost_common_scores_raw",
              "ridge_common_scores_clipped_diagnostic": "xgboost_common_scores_clipped_diagnostic",
              "ridge_own_available_scores_raw": "xgboost_own_available_scores_raw",
              "alpha_search": "parameter_search"}
    with threadpool_limits(limits=1):
        for key, group in groups.items():
            if configuration.get("site_ids") and key[0] not in configuration["site_ids"]:
                continue
            result, model, predictions = train_group(series[key], group, baselines[key], configuration,
                                                     weather[key[0]] if weather is not None else None, make_pipeline)
            result.pop("selected_alpha", None)
            for old, new in rename.items():
                if old in result:
                    result[new] = result.pop(old)
            for candidate in result.get("parameter_search", []):
                candidate.pop("alpha", None)
            result.update({"site_id": key[0], "target": key[1], "power_unit": group.get("power_unit"),
                           "validation_start": group["validation_start"], "validation_end_exclusive": group["validation_end_exclusive"]})
            if model is not None:
                path = args.output_dir / "models" / f"{key[0]}_{key[1]}.joblib"
                joblib.dump(model, path)
                result.update(model_file=str(path.relative_to(args.output_dir)), model_sha256=file_sha256(path))
            report["groups"].append(result)
            saved_rows.extend({"site_id": key[0], "target": key[1], "power_unit": group.get("power_unit"), **row} for row in predictions)
            print(f"Trained XGBoost {key[0]} {key[1]}: {result['status']}", flush=True)
    if not saved_rows:
        raise ValueError("No model predictions generated")
    report["source_unchanged"] = file_sha256(args.archive) == report["source_sha256"]
    if not report["source_unchanged"]:
        raise ValueError("Source archive changed during experiment")
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    with (args.output_dir / "validation_predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(saved_rows[0]))
        writer.writeheader()
        writer.writerows(saved_rows)
    print(f"Saved XGBoost models and validation results to {args.output_dir}")


if __name__ == "__main__":
    main()

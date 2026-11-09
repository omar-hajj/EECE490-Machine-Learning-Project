"""Provisional P90 of signed campus load minus PV; not a dispatch decision."""

import argparse
from collections import defaultdict
import csv
from datetime import datetime
import json
import math
from pathlib import Path

from .baselines import file_sha256
from .ridge import build_rows, load_inputs


def quantile_scores(actual, predicted, quantile):
    truth, forecast = list(actual), list(predicted)
    if not truth or len(truth) != len(forecast) or not 0 < quantile < 1:
        raise ValueError("Nonempty paired values and a quantile between zero and one are required")
    if not all(math.isfinite(value) for value in truth + forecast):
        raise ValueError("Quantile scoring requires finite values")
    residual = [observed - estimate for observed, estimate in zip(truth, forecast)]
    shortfalls = [value for value in residual if value > 0]
    return {"observations": len(truth),
            "pinball_loss": math.fsum(max(quantile * value, (quantile - 1) * value) for value in residual) / len(truth),
            "empirical_hourly_coverage": sum(value <= 0 for value in residual) / len(truth),
            "underforecast_hours": len(shortfalls),
            "mean_underforecast_shortfall_kw": math.fsum(shortfalls) / len(shortfalls) if shortfalls else 0}


def signed_net_series(load, pv):
    return {timestamp: load[timestamp] - pv[timestamp] for timestamp in load.keys() & pv.keys()}


def main():
    import joblib
    import numpy as np
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.pipeline import Pipeline
    from threadpoolctl import threadpool_limits
    from xgboost import XGBRegressor

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--sites", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    azm = next(site for site in json.loads(args.sites.read_text(encoding="utf-8"))["sites"] if site["site_id"] == "azm")
    if azm.get("load_meter_boundary_relative_to_pv") != "total_campus_demand_including_solar" or azm.get("power_unit_confirmed") != "kW":
        raise ValueError("Total campus demand and kW units must be confirmed before deriving net load")
    configuration = json.loads(args.config.read_text())
    q = configuration["quantile"]
    source, groups, series, _ = load_inputs(args.baseline_dir)
    if file_sha256(args.archive) != source["source_sha256"]:
        raise ValueError("Unexpected source archive")
    net = signed_net_series(series[("azm", "load")], series[("azm", "pv")])
    group = groups[("azm", "load")]
    start, end = (datetime.fromisoformat(group[name]) for name in ("validation_start", "validation_end_exclusive"))
    training, validation = build_rows(net, start, end, tuple(configuration["lag_hours"]))
    profile = defaultdict(list)
    for timestamp, value in net.items():
        if timestamp < start:
            profile[(timestamp.weekday(), timestamp.hour)].append(value)
    p90_profile = {key: float(np.quantile(values, q, method="linear")) for key, values in profile.items()}
    common = [row for row in validation if row["actual"] is not None and row["features"] is not None and
              (row["timestamp"].weekday(), row["timestamp"].hour) in p90_profile]
    if len(training) < 2 or not common:
        raise ValueError("Insufficient training/shared validation data")
    actual = [row["actual"] for row in common]
    x_train, y_train = [row["features"] for row in training], [row["actual"] for row in training]
    x_common = [row["features"] for row in common]
    search, best_model, best_score, best_parameters = [], None, None, None
    with threadpool_limits(limits=1):
        for parameters in configuration["candidate_parameters"]:
            model = Pipeline([("vectorizer", DictVectorizer(sparse=False)),
                              ("quantile", XGBRegressor(objective="reg:quantileerror", quantile_alpha=q,
                                                        tree_method="hist", n_jobs=1, random_state=42,
                                                        min_child_weight=5, reg_lambda=1, **parameters))])
            model.fit(x_train, y_train)
            scores = quantile_scores(actual, model.predict(x_common).tolist(), q)
            search.append({"parameters": parameters, "validation_scores": scores})
            if best_score is None or scores["pinball_loss"] < best_score["pinball_loss"]:
                best_model, best_score, best_parameters = model, scores, parameters
        estimates = best_model.predict(x_common).tolist()
    baseline = [p90_profile[(row["timestamp"].weekday(), row["timestamp"].hour)] for row in common]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_file = args.output_dir / "azm_signed_net_p90.joblib"
    joblib.dump(best_model, model_file)
    report = {"target": "signed_net_load_kw = campus_load_kw - solar_pv_kw", "quantile": q,
              "selection_metric": "validation_pinball_loss", "configuration": configuration,
              "selected_parameters": best_parameters, "parameter_search": search,
              "training_rows": len(training), "training_last_target": training[-1]["timestamp"].isoformat(),
              "validation_start": start.isoformat(), "validation_end_exclusive": end.isoformat(),
              "common_validation_hours": len(common), "model_scores": best_score,
              "weekday_quantile_baseline_scores": quantile_scores(actual, baseline, q),
              "source_sha256": source["source_sha256"], "source_unchanged": file_sha256(args.archive) == source["source_sha256"],
              "model_sha256": file_sha256(model_file), "test_period_scored": False,
              "generator_recommendations_generated": False,
              "input_sha256": {"hourly_data.csv": file_sha256(args.baseline_dir / "hourly_data.csv"),
                               "sites.json": file_sha256(args.sites), "config.json": file_sha256(args.config)},
              "code_sha256": {path.name: file_sha256(path) for path in (Path(__file__), Path(__file__).with_name("features.py"), Path(__file__).with_name("ridge.py"))},
              "limitations": ["Validation-tuned upper estimate, not final-test calibration.",
                              "P90 is an individual-hour target; it does not guarantee all 24 hours or instantaneous peaks.",
                              "Signed net load can be negative. No export, storage or grid-availability behavior is inferred.",
                              "Generator capacities, allowed combinations and reserve margin remain unspecified.",
                              "No weather used; no clipping or source cleaning applied to the signed target."]}
    if not report["source_unchanged"]:
        raise ValueError("Source archive changed")
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    rows = [{"timestamp_local": row["timestamp"].isoformat(), "actual_signed_net_kw": row["actual"],
             "upper_signed_net_kw": estimate, "weekday_p90_baseline_kw": prior,
             "issue_time_local": row["timestamp"].replace(hour=0).isoformat(),
             "latest_input_available_at_local": row["available_at"].isoformat()}
            for row, estimate, prior in zip(common, estimates, baseline)]
    with (args.output_dir / "validation_predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"P{q*100:.0f}: model coverage {best_score['empirical_hourly_coverage']:.1%}; weekday-quantile baseline coverage {report['weekday_quantile_baseline_scores']['empirical_hourly_coverage']:.1%}. Final test unscored.")


if __name__ == "__main__":
    main()

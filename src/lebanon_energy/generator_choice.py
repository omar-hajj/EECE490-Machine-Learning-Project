"""Score saved Azm validation forecasts by wrong-generator hours (use-linked metric).

Each method's forecast net load (load minus PV) is turned into a generator
pick with the draft policy, then compared with the configuration the actual
net load needed. All methods are compared on the same validation hours.
Only saved August predictions are read; September is never touched.
"""

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path

from .generators import choice_errors, load_policy


def _float(value):
    return float(value) if value not in (None, "") else None


def read_baseline_forecasts(baseline_dir, site_id="azm"):
    """Return ({method: {timestamp: {target: prediction}}}, {timestamp: {target: actual}})."""
    forecasts, actuals = {}, {}
    with (Path(baseline_dir) / "validation_predictions.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["site_id"] != site_id:
                continue
            stamp = datetime.fromisoformat(row["timestamp_local_unverified"])
            actual, predicted = _float(row["actual"]), _float(row["prediction"])
            if actual is not None:
                actuals.setdefault(stamp, {})[row["target"]] = actual
            if predicted is not None:
                forecasts.setdefault(row["method"], {}).setdefault(stamp, {})[row["target"]] = predicted
    return forecasts, actuals


def read_model_forecasts(run_dir, site_id="azm"):
    """Return {timestamp: {target: raw prediction}} from a Ridge/XGBoost run directory."""
    values = {}
    with (Path(run_dir) / "validation_predictions.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["site_id"] != site_id:
                continue
            predicted = _float(row["prediction_raw"])
            if predicted is not None:
                stamp = datetime.fromisoformat(row["timestamp_local_unverified"])
                values.setdefault(stamp, {})[row["target"]] = predicted
    return values


def read_net_upper(p90_dir):
    """Return ({timestamp: model upper net}, {timestamp: weekday P90 baseline net})."""
    model, baseline = {}, {}
    with (Path(p90_dir) / "validation_predictions.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            stamp = datetime.fromisoformat(row["timestamp_local"])
            model[stamp] = float(row["upper_signed_net_kw"])
            baseline[stamp] = float(row["weekday_p90_baseline_kw"])
    return model, baseline


def net_from_targets(by_time):
    return {stamp: values["load"] - values["pv"] for stamp, values in by_time.items()
            if values.get("load") is not None and values.get("pv") is not None}


def score_methods(net_forecasts, actual_net, generators, allowed, margin):
    """Score every method on the hours that all methods and the actuals share."""
    common = set(actual_net)
    for forecast in net_forecasts.values():
        common &= set(forecast)
    hours = sorted(common)
    if not hours:
        raise ValueError("No validation hours are shared by every method")
    results = {}
    for name, forecast in net_forecasts.items():
        results[name] = choice_errors([actual_net[h] for h in hours], [forecast[h] for h in hours], generators,
                                      allowed_configurations=allowed, reserve_margin_fraction=margin)
    return hours, results


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--policy", type=Path, default=Path("config/azm_generators.json"))
    parser.add_argument("--baseline-dir", type=Path, default=Path("outputs/baselines_confirmed_azm"))
    parser.add_argument("--ridge-dir", type=Path, default=Path("outputs/ridge_history_calendar"))
    parser.add_argument("--xgboost-dir", type=Path, default=Path("outputs/xgboost_history_calendar"))
    parser.add_argument("--p90-dir", type=Path, default=Path("outputs/azm_net_p90"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/generator_choice"))
    args = parser.parse_args()

    generators, allowed, margin = load_policy(args.policy)
    baselines, actuals = read_baseline_forecasts(args.baseline_dir)
    actual_net = net_from_targets(actuals)
    nets = {f"baseline_{method}": net_from_targets(values) for method, values in sorted(baselines.items())}
    for label, directory in (("ridge", args.ridge_dir), ("xgboost", args.xgboost_dir)):
        if (directory / "validation_predictions.csv").is_file():
            nets[f"{label}_point"] = net_from_targets(read_model_forecasts(directory))
    if (args.p90_dir / "validation_predictions.csv").is_file():
        nets["xgboost_p90_net"], nets["baseline_weekday_p90_net"] = read_net_upper(args.p90_dir)
    hours, results = score_methods(nets, actual_net, generators, allowed, margin)

    report = {"site_id": "azm", "status": "validation_only_draft_policy",
              "validation_start": hours[0].isoformat(), "validation_last_hour": hours[-1].isoformat(),
              "common_hours": len(hours), "policy_file": str(args.policy), "reserve_margin_fraction": margin,
              "capacities_kw": {g.generator_id: g.usable_capacity_kw for g in generators},
              "allowed_configurations": allowed, "test_period_scored": False, "methods": results}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [f"Wrong-generator hours on {len(hours)} shared August validation hours "
             f"(reserve margin {margin:.0%}).", "",
             "| Method | Undersized (overload risk) | Oversized (wasted fuel) | Right-sized |",
             "| --- | ---: | ---: | ---: |"]
    for name, result in results.items():
        lines.append(f"| {name} | {result['undersized_hours']} ({result['undersized_share']:.1%}) | "
                     f"{result['oversized_hours']} ({result['oversized_share']:.1%}) | "
                     f"{result['right_sized_hours']} ({result['right_sized_share']:.1%}) |")
    (args.output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

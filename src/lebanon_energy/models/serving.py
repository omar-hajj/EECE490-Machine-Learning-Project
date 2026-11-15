"""Build the frozen Azm model bundle that the API serves.

The method was chosen with the rolling-origin check (models/walk_forward.py,
WEEK2_RESULTS.md): a holiday-aware Ridge forecast of net load, plus a margin
taken from the forecast's own errors on recent days as the upper estimate
used to size the generator.

Nothing at or after --train-end is read. The default is the start of the
validation month, so August can be replayed honestly in the interface.
"""

import argparse
from datetime import datetime, timedelta, timezone
import importlib.metadata
import json
from pathlib import Path

from ..data.calendar_days import COVERED_PERIODS, load_public_holidays
from ..data.preparation import file_sha256
from ..features.holidays import holiday_aware_features
from .baselines import fit_weekday_profile, predict
from .quantiles import signed_net_series
from .ridge import load_inputs, make_pipeline
from .walk_forward import upper_rank_value

NET_METHODS = ("ridge", "last_week", "weekday_average")


def fit_ridge(series, holidays, end, alpha):
    rows, targets = [], []
    for stamp, value in sorted(series.items()):
        if stamp >= end:
            continue
        features, _ = holiday_aware_features(series, stamp, holidays)
        if features is not None:
            rows.append(features)
            targets.append(value)
    if len(rows) < 2:
        raise ValueError("Too little history to fit the served model")
    return make_pipeline(alpha).fit(rows, targets), len(rows)


def stored_margins(net, holidays, end, *, alpha, quantile, window_days, fallback_window_days):
    """Per-method, per-hour margins from out-of-sample errors on the last days before `end`.

    Each of those days is forecast using earlier hours only, as in the
    rolling-origin check. Returns the margins and the Ridge errors by hour;
    the API adds Ridge errors from days after `end` as readings arrive.
    The two fallback methods cannot be refreshed that way, so their margins
    come from a longer window and are never below zero.
    """
    residuals = {method: {hour: [] for hour in range(24)} for method in NET_METHODS}
    by_hour = {}
    for back in range(max(window_days, fallback_window_days), 0, -1):
        day = end - timedelta(days=back)
        model = fit_ridge(net, holidays, day, alpha)[0] if back <= window_days else None
        profile = fit_weekday_profile(net, day)
        for hour in range(24):
            stamp = day + timedelta(hours=hour)
            actual = net.get(stamp)
            if actual is None:
                continue
            features = holiday_aware_features(net, stamp, holidays)[0] if model is not None else None
            if features is not None:
                by_hour[stamp] = actual - float(model.predict([features])[0])
                residuals["ridge"][hour].append(by_hour[stamp])
            if back <= fallback_window_days:
                for method in ("last_week", "weekday_average"):
                    result = predict(net, profile, stamp, method)
                    if result is not None:
                        residuals[method][hour].append(actual - result[0])
    margins = {method: {hour: max(upper_rank_value(values, quantile), 0.0) if method != "ridge"
                        else upper_rank_value(values, quantile) for hour, values in hours.items() if values}
               for method, hours in residuals.items()}
    return margins, by_hour


def build(series, holidays, end, configuration, policy, source_sha256):
    load, pv = series["load"], series["pv"]
    net = signed_net_series(load, pv)
    alpha, quantile = configuration["ridge_alpha"], configuration["quantile"]
    window = configuration["recent_error_window_days"]
    net_model, net_rows = fit_ridge(net, holidays, end, alpha)
    load_model, _ = fit_ridge(load, holidays, end, alpha)
    margins, errors = stored_margins(net, holidays, end, alpha=alpha, quantile=quantile, window_days=window,
                                     fallback_window_days=configuration["fallback_error_window_days"])
    return {
        "site_id": "azm", "training_end_exclusive": end, "training_rows": net_rows,
        "models": {"net": net_model, "load": load_model},
        "profiles": {name: fit_weekday_profile(values, end)
                     for name, values in (("load", load), ("pv", pv), ("net", net))},
        "stored_margins_kw": margins, "stored_ridge_errors_kw": errors,
        "quantile": quantile, "recent_error_window_days": window,
        "recent_error_minimum_days": configuration["recent_error_minimum_days"],
        "holidays": sorted(holidays), "holiday_covered_periods": list(COVERED_PERIODS),
        "generator_policy": policy, "ridge_alpha": alpha,
        "selection_basis": "Rolling-origin check on May-August 2026 (WEEK2_RESULTS.md); September not read",
        "source_sha256": source_sha256,
        "versions": {name: importlib.metadata.version(name) for name in ("scikit-learn", "numpy", "joblib")},
    }


def main():
    import joblib
    from threadpoolctl import threadpool_limits

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-dir", type=Path, default=Path("outputs/baselines_confirmed_azm"))
    parser.add_argument("--config", type=Path, default=Path("config/walk_forward.json"))
    parser.add_argument("--policy", type=Path, default=Path("config/azm_generators.json"))
    parser.add_argument("--train-end", type=datetime.fromisoformat, default=None,
                        help="Midnight; nothing at or after it is read (default: start of validation)")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/serving"))
    args = parser.parse_args()
    source, groups, all_series, _ = load_inputs(args.baseline_dir)
    end = args.train_end or datetime.fromisoformat(groups[("azm", "load")]["validation_start"])
    if end > datetime.fromisoformat(groups[("azm", "load")]["validation_end_exclusive"]):
        raise ValueError("Training cannot extend into the reserved test month")
    configuration = json.loads(args.config.read_text(encoding="utf-8"))
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    series = {target: all_series[("azm", target)] for target in ("load", "pv")}
    with threadpool_limits(limits=1):
        bundle = build(series, set(load_public_holidays()), end, configuration, policy, source["source_sha256"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / "azm_bundle.joblib"
    joblib.dump(bundle, path)
    report = {"built_utc": datetime.now(timezone.utc).isoformat(), "training_end_exclusive": end.isoformat(),
              "training_rows": bundle["training_rows"], "configuration": configuration,
              "policy_status": policy["status"], "model_sha256": file_sha256(path),
              "input_sha256": file_sha256(args.baseline_dir / "hourly_data.csv"),
              "source_sha256": source["source_sha256"], "versions": bundle["versions"],
              "stored_margin_kw_range": {method: [min(values.values()), max(values.values())]
                                         for method, values in bundle["stored_margins_kw"].items()},
              "test_period_scored": False}
    (args.output_dir / "bundle.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved {path} (trained on {bundle['training_rows']} hours before {end.date()})")


if __name__ == "__main__":
    main()

"""Tune the served model the way course chapter 6 prescribes: on validation folds, never on the test month.

Two things are tuned, both with the daily rolling-origin procedure on data
before September (folds = May, June, July, August):

1. The point forecast: regularization strength (Ridge alpha), L1 instead of
   L2 (Lasso), engineered features, and an ensemble with XGBoost. Selected
   by mean absolute error averaged over the folds.
2. The sizing rule: the quantile and look-back window of the recent-error
   margin, and the reserve margin. This is a threshold sweep, like moving
   along a ROC curve: every setting trades hours picked too small against
   hours picked too large. Selected as the setting with the fewest oversized
   hours among those at least as safe as the current rule.

The test month was opened once before this tuning existed (FINAL_RESULTS.md).
--rescore-test re-reads September to score the tuned setting. That number is
NOT a clean test result: the ideas tried here were suggested by the September
failure. It is reported as an indication only.
"""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

from ..data.calendar_days import load_public_holidays
from ..features.holidays import holiday_aware_features
from ..generators.policy import Generator, pick_errors, recommend
from .quantiles import signed_net_series
from .ridge import load_inputs
from .walk_forward import recent_error_margin

FEATURE_SETS = {
    "current": (),
    "+48h": ("lag_48h",),
    "+yesterday level": ("yesterday_mean", "yesterday_max"),
    "+7-day mean": ("week_mean_same_hour",),
    "+similar day": ("similar_day_same_hour",),
    "+similar day, 7-day mean": ("similar_day_same_hour", "week_mean_same_hour"),
    "all extras": ("lag_48h", "yesterday_mean", "yesterday_max", "week_mean_same_hour", "similar_day_same_hour"),
}
RIDGE_ALPHAS = (0.1, 1.0, 10.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0)
LASSO_ALPHAS = (0.2, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0)
QUANTILES = (0.7, 0.8, 0.85, 0.9, 0.95)
WINDOWS = (7, 14, 21, 28)
RESERVES = (0.0, 0.05, 0.10)


def _day_type(day, holidays):
    return "off" if day.weekday() >= 5 or day in holidays else "working"


def extra_features(series, stamp, holidays, names):
    """Engineered inputs, all built from hours that finished before the midnight issue time."""
    issue = stamp.replace(hour=0)
    values = {}
    for name in names:
        if name == "lag_48h":
            value = series.get(stamp - timedelta(hours=48))
        elif name in ("yesterday_mean", "yesterday_max"):
            day = [series.get(issue - timedelta(hours=back)) for back in range(1, 25)]
            day = [v for v in day if v is not None]
            value = None if len(day) < 20 else (math.fsum(day) / len(day) if name == "yesterday_mean" else max(day))
        elif name == "week_mean_same_hour":
            week = [series.get(stamp - timedelta(days=back)) for back in range(1, 8)]
            week = [v for v in week if v is not None]
            value = math.fsum(week) / len(week) if len(week) >= 5 else None
        elif name == "similar_day_same_hour":
            # Same hour on the most recent earlier day of the same type (working day or day off).
            # Monday morning then looks at Friday instead of Sunday.
            value, wanted = None, _day_type(stamp.date(), holidays)
            for back in range(1, 8):
                earlier = stamp - timedelta(days=back)
                if _day_type(earlier.date(), holidays) == wanted:
                    value = series.get(earlier)
                    break
        else:
            raise ValueError(f"Unknown feature {name}")
        if value is None:
            return None
        values[name] = value
    return values


def build_matrix(series, holidays, names, start, end):
    """Feature matrix for every hour in [start, end) that has all inputs; target is None when unobserved."""
    from sklearn.feature_extraction import DictVectorizer

    stamps, rows = [], []
    stamp = start
    while stamp < end:
        features, _ = holiday_aware_features(series, stamp, holidays)
        extras = extra_features(series, stamp, holidays, names) if features is not None else None
        if features is not None and extras is not None:
            stamps.append(stamp)
            rows.append({**features, **extras})
        stamp += timedelta(hours=1)
    matrix = DictVectorizer(sparse=False).fit_transform(rows)
    return stamps, matrix, [series.get(s) for s in stamps]


def rolling_predictions(stamps, matrix, targets, first_day, end_day, make_model):
    """{timestamp: forecast}; each day uses a model fitted on observed hours before that day."""
    import numpy as np

    observed = np.array([t is not None for t in targets])
    y = np.array([t if t is not None else 0.0 for t in targets])
    times = np.array([s.timestamp() for s in stamps])
    predictions = {}
    day = first_day
    while day < end_day:
        train = (times < day.timestamp()) & observed
        today = (times >= day.timestamp()) & (times < (day + timedelta(days=1)).timestamp())
        if today.any() and train.sum() >= 100:
            model = make_model().fit(matrix[train], y[train])
            for stamp, value in zip(np.array(stamps)[today], model.predict(matrix[today])):
                predictions[stamp] = float(value)
        day += timedelta(days=1)
    return predictions


def linear_model(kind, alpha):
    from sklearn.linear_model import Lasso, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    estimator = Ridge(alpha=alpha, solver="cholesky") if kind == "ridge" else Lasso(alpha=alpha, max_iter=5000)
    return lambda: make_pipeline(StandardScaler(), estimator)


def fold_scores(series, predictions, hours, folds):
    """Mean absolute error per fold and overall on the given hours."""
    scores = {}
    for name, (start, end) in folds.items():
        errors = [abs(series[s] - predictions[s]) for s in hours if start <= s < end]
        scores[name] = math.fsum(errors) / len(errors) if errors else None
    usable = [value for value in scores.values() if value is not None]
    everything = [series[s] - predictions[s] for s in hours]
    return {"fold_mae": scores, "mean_fold_mae": math.fsum(usable) / len(usable),
            "fold_spread": max(usable) - min(usable),
            "rmse": math.sqrt(math.fsum(e * e for e in everything) / len(everything))}


def sizing_sweep(series, predictions, policy, first_day, end_day, score_from):
    """Wrong-generator hours for every quantile / window / reserve setting, on the same hours."""
    generators = [Generator(item["generator_id"], float(item["usable_capacity_kw"])) for item in policy["generators"]]
    allowed = policy["allowed_configurations"]
    residuals = {s: series[s] - p for s, p in predictions.items() if s in series}
    uppers = {}
    for quantile in QUANTILES:
        for window in WINDOWS:
            table = {}
            day = first_day
            while day < end_day:
                for hour in range(24):
                    stamp = day + timedelta(hours=hour)
                    if stamp not in predictions:
                        continue
                    margin = recent_error_margin(residuals, day, hour, quantile=quantile, window_days=window,
                                                 minimum_days=min(7, window))
                    if margin is not None:
                        table[stamp] = predictions[stamp] + margin
                day += timedelta(days=1)
            uppers[(quantile, window)] = table
    hours = sorted(s for s in series if s >= score_from and all(s in table for table in uppers.values()))
    actual = [series[s] for s in hours]
    results = []
    for (quantile, window), table in uppers.items():
        for reserve in RESERVES:
            picks = [recommend(max(table[s], 0.0), generators, allowed_configurations=allowed,
                               reserve_margin_fraction=reserve)["selected_capacity_kw"] for s in hours]
            outcome = pick_errors(actual, picks, generators, allowed_configurations=allowed)
            results.append({"quantile": quantile, "window_days": window, "reserve": reserve, "hours": len(hours),
                            "coverage": sum(a <= table[s] for a, s in zip(actual, hours)) / len(hours),
                            "undersized": outcome["undersized_hours"], "oversized": outcome["oversized_hours"],
                            "right_sized": outcome["right_sized_hours"]})
    return results


def choose_sizing(results, current):
    """Fewest oversized hours among settings no less safe than the current one (ties: fewer undersized)."""
    reference = next(r for r in results if all(r[k] == current[k] for k in ("quantile", "window_days", "reserve")))
    safe = [r for r in results if r["undersized"] <= reference["undersized"]]
    return reference, min(safe, key=lambda r: (r["oversized"], r["undersized"]))


def main():
    from threadpoolctl import threadpool_limits

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-dir", type=Path, default=Path("outputs/baselines_confirmed_azm"))
    parser.add_argument("--config", type=Path, default=Path("config/walk_forward.json"))
    parser.add_argument("--policy", type=Path, default=Path("config/azm_generators.json"))
    parser.add_argument("--walk-forward", type=Path, default=Path("outputs/walk_forward/predictions.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/tuning"))
    parser.add_argument("--rescore-test", type=Path, metavar="ARCHIVE",
                        help="Also score the chosen settings on September (NOT a clean test; see module docstring)")
    args = parser.parse_args()
    configuration = json.loads(args.config.read_text(encoding="utf-8"))
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    _, groups, series_by_site, _ = load_inputs(args.baseline_dir)
    net = signed_net_series(series_by_site[("azm", "load")], series_by_site[("azm", "pv")])
    holidays = set(load_public_holidays())
    first_day = datetime.fromisoformat(configuration["first_origin"])
    end_day = datetime.fromisoformat(groups[("azm", "load")]["validation_end_exclusive"])
    folds = {f"{datetime(2026, month, 1):%B}": (datetime(2026, month, 1), datetime(2026, month + 1, 1))
             for month in range(first_day.month, end_day.month)}
    start = min(net).replace(hour=0) + timedelta(days=8)

    candidates = {}
    with threadpool_limits(limits=1):
        for set_name, names in FEATURE_SETS.items():
            stamps, matrix, targets = build_matrix(net, holidays, names, start, end_day)
            grid = [("ridge", alpha) for alpha in RIDGE_ALPHAS]
            if set_name in ("current", "+similar day, 7-day mean", "all extras"):
                grid += [("lasso", alpha) for alpha in LASSO_ALPHAS]
            for kind, alpha in grid:
                candidates[(set_name, kind, alpha)] = rolling_predictions(stamps, matrix, targets, first_day, end_day,
                                                                          linear_model(kind, alpha))
            print(f"Tried feature set '{set_name}' ({matrix.shape[1]} columns)", flush=True)
    xgboost = {}
    if args.walk_forward.is_file():
        with args.walk_forward.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["xgboost"] != "":
                    xgboost[datetime.fromisoformat(row["timestamp_local"])] = float(row["xgboost"])
    hours = sorted(s for s in net if first_day + timedelta(days=7) <= s < end_day
                   and all(s in predictions for predictions in candidates.values()) and (not xgboost or s in xgboost))
    table = [{"features": key[0], "model": key[1], "alpha": key[2], **fold_scores(net, predictions, hours, folds)}
             for key, predictions in candidates.items()]
    table.sort(key=lambda row: row["mean_fold_mae"])
    current_key = ("current", "ridge", float(configuration["ridge_alpha"]))
    current = next(r for r in table if (r["features"], r["model"], r["alpha"]) == current_key)
    best = table[0]
    best_key = (best["features"], best["model"], best["alpha"])
    ensemble = None
    if xgboost:
        blend = {s: (candidates[best_key][s] + xgboost[s]) / 2 for s in hours}
        ensemble = {"features": best["features"], "model": f"average of {best['model']} and xgboost", "alpha": best["alpha"],
                    **fold_scores(net, blend, hours, folds)}
        only_trees = {"features": "current", "model": "xgboost", "alpha": None, **fold_scores(net, xgboost, hours, folds)}
    report = {"run_time_utc": datetime.now(timezone.utc).isoformat(), "site_id": "azm",
              "tuned_on": "rolling-origin folds before September 2026", "common_hours": len(hours),
              "folds": list(folds), "candidates_tried": len(table), "current_point": current, "best_point": best,
              "ensemble": ensemble, "xgboost_reference": only_trees if xgboost else None,
              "relative_improvement": 1 - best["mean_fold_mae"] / current["mean_fold_mae"], "point_table": table}

    # What the chosen model keeps: Lasso sets unhelpful coefficients exactly to zero.
    from sklearn.feature_extraction import DictVectorizer
    rows = []
    for stamp in sorted(net):
        features, _ = holiday_aware_features(net, stamp, holidays)
        extras = extra_features(net, stamp, holidays, FEATURE_SETS[best_key[0]]) if features is not None else None
        if features is not None and extras is not None:
            rows.append(({**features, **extras}, net[stamp]))
    vectorizer = DictVectorizer(sparse=False)
    fitted = linear_model(best_key[1], best_key[2])().fit(vectorizer.fit_transform([r for r, _ in rows]), [t for _, t in rows])
    scaler, estimator = fitted.steps[0][1], fitted.steps[1][1]
    names = list(vectorizer.get_feature_names_out())
    kept = {name: float(c / sc) for name, c, sc in zip(names, estimator.coef_, scaler.scale_) if abs(c) > 1e-9}
    report["best_point_coefficients"] = {
        "rows": len(rows), "columns": len(names), "nonzero": len(kept),
        "hour_of_week_columns_kept": sum(name.startswith("hour_of_week=") for name in kept),
        "kw_per_unit_of_input": {name: value for name, value in kept.items() if not name.startswith("hour_of_week=")}}

    current_rule = {"quantile": configuration["quantile"], "window_days": configuration["recent_error_window_days"],
                    "reserve": float(policy["reserve_margin_fraction"])}
    score_from = first_day + timedelta(days=28)
    for label, key in (("current_model", current_key), ("best_model", best_key)):
        sweep = sizing_sweep(net, candidates[key], policy, first_day, end_day, score_from)
        reference, chosen = choose_sizing(sweep, current_rule)
        report[f"sizing_{label}"] = {"current_setting": reference, "chosen_setting": chosen, "sweep": sweep}

    if args.rescore_test is not None:
        from ..evaluation.final_test import read_net_load

        protocol = json.loads(Path("config/baseline.json").read_text(encoding="utf-8"))
        sites = json.loads(Path("config/sites.json").read_text(encoding="utf-8"))["sites"]
        test_start, test_end = end_day, datetime.fromisoformat(protocol["azm"]["reserved_test_end_exclusive"])
        full, _ = read_net_load(args.rescore_test, sites, protocol, test_end)
        rescored = {}
        with threadpool_limits(limits=1):
            for label, key in (("current", current_key), ("tuned", best_key)):
                stamps, matrix, targets = build_matrix(full, holidays, FEATURE_SETS[key[0]], start, test_end)
                rescored[label] = rolling_predictions(stamps, matrix, targets, test_start - timedelta(days=28), test_end,
                                                      linear_model(key[1], key[2]))
        test_hours = sorted(s for s in full if s >= test_start and all(s in p for p in rescored.values()))
        generators = [Generator(i["generator_id"], float(i["usable_capacity_kw"])) for i in policy["generators"]]
        outcome = {"warning": "Post-hoc: September was opened before this tuning. Indication only, not a test result.",
                   "hours": len(test_hours)}
        for label, setting_key in (("current", "sizing_current_model"), ("tuned", "sizing_best_model")):
            predictions = rescored[label]
            errors = [full[s] - predictions[s] for s in test_hours]
            entry = {"mae": math.fsum(abs(e) for e in errors) / len(errors), "mbe": math.fsum(errors) / len(errors),
                     "rmse": math.sqrt(math.fsum(e * e for e in errors) / len(errors)),
                     "nmae": math.fsum(abs(e) for e in errors) / math.fsum(abs(full[s]) for s in test_hours)}
            residuals = {s: full[s] - p for s, p in predictions.items() if s in full}
            for rule_label, rule in (("current_rule", current_rule),
                                     ("tuned_rule", report[setting_key]["chosen_setting"])):
                picks, covered = [], 0
                for s in test_hours:
                    margin = recent_error_margin(residuals, s.replace(hour=0), s.hour, quantile=rule["quantile"],
                                                 window_days=rule["window_days"], minimum_days=min(7, rule["window_days"]))
                    upper = predictions[s] + (margin or 0.0)
                    covered += full[s] <= upper
                    picks.append(recommend(max(upper, 0.0), generators, allowed_configurations=policy["allowed_configurations"],
                                           reserve_margin_fraction=rule["reserve"])["selected_capacity_kw"])
                choice = pick_errors([full[s] for s in test_hours], picks, generators,
                                     allowed_configurations=policy["allowed_configurations"])
                entry[rule_label] = {"quantile": rule["quantile"], "window_days": rule["window_days"],
                                     "reserve": rule["reserve"], "coverage": covered / len(test_hours),
                                     "undersized": choice["undersized_hours"], "oversized": choice["oversized_hours"],
                                     "right_sized": choice["right_sized_hours"]}
            outcome[label] = entry
        report["post_hoc_september"] = outcome

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in ("point_table",) and not k.startswith("sizing_")}, indent=2))
    print("Top 8 point candidates:")
    for row in table[:8]:
        print(f"  {row['features']:28s} {row['model']:6s} alpha={row['alpha']:<7} mean fold MAE {row['mean_fold_mae']:.2f} "
              f"spread {row['fold_spread']:.1f} rmse {row['rmse']:.1f}")
    for label in ("sizing_current_model", "sizing_best_model"):
        print(label, json.dumps({k: report[label][k] for k in ("current_setting", "chosen_setting")}))


if __name__ == "__main__":
    main()

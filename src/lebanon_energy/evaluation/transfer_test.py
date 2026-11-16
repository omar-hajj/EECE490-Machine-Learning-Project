"""Clean test of the tuning procedure on a month nothing has seen: Household 3, July 2025.

Azm's September was opened before the model was tuned, so the tuned
model's September score is not a fair test (MODEL_TUNING.md). Household 3's
July has never been read by any script. This test asks whether the tuning
*procedure* generalises:

  1. Selection, on data before the test month only: the same candidate grid
     and rule as scripts/tune_model.py (lowest mean absolute error across
     monthly rolling-origin folds).
  2. Test, once: the untuned setting (Ridge, alpha 1, original features),
     the selected setting, and the "same hour last week" baseline are
     forecast day by day through the test month and scored on the same hours.

Lasso strength is expressed relative to the spread of the target, because
Household 3 is in watts and Azm in kilowatts.

It is a different site (a home, not a campus), so it does not measure how
good the tuned model is at Azm.

Without --open-test-set this rehearses on the validation month (June) and
reads nothing from July. With it, the test runs once and refuses to run
again while results/final_test_household_3.json exists.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
from statistics import pstdev
from zipfile import ZipFile

from ..data.calendar_days import load_public_holidays
from ..data.preparation import _site_records, file_sha256, hourly_means, mask_frozen_readings
from ..models.tuning import (FEATURE_SETS, RIDGE_ALPHAS, build_matrix, fold_scores, linear_model,
                             rolling_predictions)
from ..models.walk_forward import recent_error_margin
from .course_metrics import paired_error_z_test, regression_metrics

REPOSITORY = Path(__file__).resolve().parents[3]
RECORD = REPOSITORY / "results" / "final_test_household_3.json"
SITE = "household_3"
# Lasso strengths as a share of the target's standard deviation (Azm's chosen 2 kW is about 0.045 of its spread).
LASSO_RELATIVE = (0.005, 0.01, 0.02, 0.045, 0.07, 0.11, 0.18)
LASSO_FEATURE_SETS = ("current", "+similar day, 7-day mean", "all extras")
CURRENT = ("current", "ridge", 1.0)
WARM_UP_DAYS = 28


def read_load(archive_path, sites, protocol, end):
    """Household 3 hourly load (W) from the source ZIP, keeping nothing at or after `end`."""
    site = next(item for item in sites if item["site_id"] == SITE)
    profile = {**protocol["other_sites"], "validation_end_exclusive": end.isoformat()}
    counters = {"timestamp_interpretations": Counter(), "positive_intervals_seconds": Counter(),
                "reserved_or_later_rows_not_used": 0, "workbooks_read": 0, "reserved_workbooks_not_opened": []}
    with ZipFile(archive_path) as archive:
        records = list(_site_records(archive, site, profile, counters))
    rule = protocol.get("frozen_readings")
    if rule and SITE in rule["site_ids"]:
        records, _ = mask_frozen_readings(records, targets=profile["targets"], sampling_minutes=profile["sampling_minutes"],
                                          minimum_consecutive_readings=rule["minimum_consecutive_readings"])
    hourly, preparation = hourly_means(records, targets=profile["targets"],
                                       sampling_minutes=profile["sampling_minutes"], cutoff=end)
    load = hourly["load"]
    if load and max(load) >= end:
        raise ValueError("Prepared data extends past the requested end")
    return load, {"rows_read": preparation["included_raw_records"], "complete_hours": len(load),
                  "workbooks_read": counters["workbooks_read"],
                  "workbooks_not_opened": counters["reserved_workbooks_not_opened"]}


def select(series, holidays, first_day, end, progress=None):
    """Pick the setting with the lowest mean fold MAE, using hours before `end` only."""
    known = {stamp: value for stamp, value in series.items() if stamp < end}
    spread = pstdev(known.values())
    start = min(known).replace(hour=0) + timedelta(days=8)
    candidates = {}
    for set_name, names in FEATURE_SETS.items():
        stamps, matrix, targets = build_matrix(known, holidays, names, start, end)
        grid = [("ridge", alpha) for alpha in RIDGE_ALPHAS]
        if set_name in LASSO_FEATURE_SETS:
            grid += [("lasso", share * spread) for share in LASSO_RELATIVE]
        for kind, alpha in grid:
            candidates[(set_name, kind, alpha)] = rolling_predictions(stamps, matrix, targets, first_day, end,
                                                                      linear_model(kind, alpha))
        if progress:
            progress(set_name)
    hours = sorted(s for s in known if s >= first_day and all(s in p for p in candidates.values()))
    folds, month = {}, first_day.replace(day=1)
    while month < end:
        following = (month + timedelta(days=32)).replace(day=1)
        if sum(month <= s < following for s in hours) >= 100:
            folds[f"{month:%B %Y}"] = (month, following)
        month = following
    table = [{"features": key[0], "model": key[1], "alpha": key[2], **fold_scores(known, predictions, hours, folds)}
             for key, predictions in candidates.items()]
    table.sort(key=lambda row: row["mean_fold_mae"])
    best = table[0]
    current = next(row for row in table if (row["features"], row["model"], row["alpha"]) == CURRENT)
    return (best["features"], best["model"], best["alpha"]), {
        "target_standard_deviation": spread, "common_hours": len(hours), "folds": list(folds),
        "candidates_tried": len(table), "current": current, "selected": best,
        "validation_improvement": 1 - best["mean_fold_mae"] / current["mean_fold_mae"], "top_5": table[:5]}


def test(series, holidays, settings, start, end, quantile=0.9, window_days=28):
    """Score each setting and the last-week baseline on the same hours of [start, end)."""
    first = min(series).replace(hour=0) + timedelta(days=8)
    forecasts = {}
    for label, (set_name, kind, alpha) in settings.items():
        stamps, matrix, targets = build_matrix(series, holidays, FEATURE_SETS[set_name], first, end)
        forecasts[label] = rolling_predictions(stamps, matrix, targets, start - timedelta(days=WARM_UP_DAYS), end,
                                               linear_model(kind, alpha))
    hours = sorted(s for s in series if start <= s < end and all(s in p for p in forecasts.values())
                   and s - timedelta(hours=168) in series)
    actual = [series[s] for s in hours]
    results = {"hours": len(hours), "mean_load": math.fsum(actual) / len(actual), "methods": {}}
    results["methods"]["last_week"] = regression_metrics(actual, [series[s - timedelta(hours=168)] for s in hours])
    for label, predictions in forecasts.items():
        scores = regression_metrics(actual, [predictions[s] for s in hours])
        residuals = {s: series[s] - p for s, p in predictions.items() if s in series}
        covered, counted = 0, 0
        for s in hours:
            margin = recent_error_margin(residuals, s.replace(hour=0), s.hour, quantile=quantile,
                                         window_days=window_days, minimum_days=7)
            if margin is not None:
                counted += 1
                covered += series[s] <= predictions[s] + margin
        scores["upper_coverage"] = covered / counted if counted else None
        results["methods"][label] = scores
    labels = list(forecasts)
    if len(labels) == 2:
        results["tuned_vs_untuned"] = paired_error_z_test(actual, [forecasts[labels[1]][s] for s in hours],
                                                          [forecasts[labels[0]][s] for s in hours])
    results["tuned_vs_last_week"] = paired_error_z_test(actual, [forecasts[labels[-1]][s] for s in hours],
                                                        [series[s - timedelta(hours=168)] for s in hours])
    return results


def summary_markdown(report):
    selection, outcome = report["selection"], report["test"]
    chosen = selection["selected"]
    lines = [f"# Household 3 transfer test of the tuning procedure ({report['mode']})", "",
             f"Scored month: {report['scored_period'][0][:10]} to {report['scored_period'][1][:10]} (exclusive), "
             f"{outcome['hours']} hours, mean load {outcome['mean_load']:.0f} W.", "",
             f"Selected on {len(selection['folds'])} earlier monthly folds from {selection['candidates_tried']} candidates: "
             f"**{chosen['model']}, alpha {chosen['alpha']:.3g}, features '{chosen['features']}'** "
             f"(validation MAE {chosen['mean_fold_mae']:.1f} W against {selection['current']['mean_fold_mae']:.1f} W "
             f"untuned, {selection['validation_improvement']:.1%} lower).", "",
             "| Method | MBE (W) | MAE (W) | RMSE (W) | MAE / mean load | Upper-estimate coverage |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    names = {"last_week": "Same hour last week", "untuned": "Untuned (Ridge, alpha 1)", "tuned": "Tuned by the procedure"}
    for label, scores in outcome["methods"].items():
        coverage = scores.get("upper_coverage")
        lines.append(f"| {names[label]} | {scores['mbe']:+.0f} | {scores['mae']:.0f} | {scores['rmse']:.0f} | "
                     f"{scores['nmae']:.1%} | {'' if coverage is None else f'{coverage:.1%}'} |")
    for key, title in (("tuned_vs_untuned", "Tuned against untuned"), ("tuned_vs_last_week", "Tuned against last week")):
        check = outcome[key]
        lines += ["", f"{title}: mean difference in absolute error {check['mean_difference_kw']:+.1f} W, "
                  f"z = {check['z']:+.2f}, p = {check['p_value_two_sided']:.3f} (negative favours the tuned model)."]
    return "\n".join(lines) + "\n"


def main():
    from threadpoolctl import threadpool_limits

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--open-test-set", action="store_true", help="Read and score July 2025. Allowed once.")
    parser.add_argument("--protocol", type=Path, default=Path("config/baseline.json"))
    parser.add_argument("--sites", type=Path, default=Path("config/sites.json"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    sites = json.loads(args.sites.read_text(encoding="utf-8"))["sites"]
    profile = protocol["other_sites"]
    validation_start = datetime.fromisoformat(profile["validation_start"])
    test_start = datetime.fromisoformat(profile["validation_end_exclusive"])
    test_end = datetime.fromisoformat(profile["reserved_test_end_exclusive"])
    if args.open_test_set:
        if RECORD.exists():
            raise SystemExit(f"Refusing to run: {RECORD} exists, so this test set was already opened.")
        start, end, mode = test_start, test_end, "final_test"
    else:
        start, end, mode = validation_start, test_start, "rehearsal_on_validation_month"
    output_dir = args.output_dir or Path(f"outputs/transfer_test{'' if args.open_test_set else '_rehearsal'}")
    source_sha256 = file_sha256(args.archive)
    series, preparation = read_load(args.archive, sites, protocol, end)
    holidays = set(load_public_holidays())
    first_day = min(series).replace(hour=0) + timedelta(days=16)
    with threadpool_limits(limits=1):
        chosen, selection = select(series, holidays, first_day, start,
                                   progress=lambda name: print(f"Selection: tried '{name}'", flush=True))
        outcome = test(series, holidays, {"untuned": CURRENT, "tuned": chosen}, start, end)
    report = {"run_time_utc": datetime.now(timezone.utc).isoformat(), "mode": mode, "site_id": SITE, "unit": "W",
              "scored_period": [start.isoformat(), end.isoformat()], "selection_uses_data_before": start.isoformat(),
              "test_period_scored": bool(args.open_test_set), "preparation": preparation,
              "source_sha256": source_sha256, "source_unchanged": file_sha256(args.archive) == source_sha256,
              "code_sha256": {name: file_sha256(path) for name, path in (
                  ("transfer_test.py", Path(__file__)),
                  ("tuning.py", REPOSITORY / "src" / "lebanon_energy" / "models" / "tuning.py"))},
              "selection": selection, "test": outcome}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output_dir / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
    if args.open_test_set:
        RECORD.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Recorded in {RECORD}. Do not rerun.")
    print(summary_markdown(report))


if __name__ == "__main__":
    main()

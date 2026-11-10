"""Score saved validation forecasts on daily peak error for Azm and Household 3.

Reads the baseline, Ridge and XGBoost validation predictions already saved
under outputs/. Every method is scored on the same hours, and only on days
where all 24 of those hours exist. Final test months are not involved.
"""

import argparse
import csv
from datetime import datetime
import json
from pathlib import Path

from ..evaluation.metrics import daily_peak_scores, score

SITES = {"azm": "August 2026", "household_3": "June 2025"}


def read_predictions(baseline_dir, model_dirs, site_id, target="load"):
    """{method: {timestamp: (actual, prediction)}} for one site and target."""
    methods = {}
    with (Path(baseline_dir) / "validation_predictions.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["site_id"] == site_id and row["target"] == target and row["actual"] and row["prediction"]:
                methods.setdefault(f"baseline_{row['method']}", {})[
                    datetime.fromisoformat(row["timestamp_local_unverified"])] = (float(row["actual"]), float(row["prediction"]))
    for label, directory in model_dirs.items():
        path = Path(directory) / "validation_predictions.csv"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["site_id"] == site_id and row["target"] == target and row["actual"] and row["prediction_raw"]:
                    methods.setdefault(label, {})[
                        datetime.fromisoformat(row["timestamp_local_unverified"])] = (float(row["actual"]), float(row["prediction_raw"]))
    return methods


def score_site(methods):
    common = sorted(set.intersection(*(set(values) for values in methods.values())))
    if not common:
        raise ValueError("No hours shared by every method")
    results = {}
    for name, values in methods.items():
        rows = [(t, *values[t]) for t in common]
        hourly = score([a for _, a, _ in rows], [p for _, _, p in rows])
        results[name] = {"largest_hourly_error": hourly.maximum_absolute_error, "nmae": hourly.nmae,
                         **daily_peak_scores(rows)}
    return {"shared_hours": len(common), "methods": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-dir", type=Path, default=Path("outputs/baselines_confirmed_azm"))
    parser.add_argument("--ridge-dir", type=Path, default=Path("outputs/ridge_history_calendar"))
    parser.add_argument("--xgboost-dir", type=Path, default=Path("outputs/xgboost_history_calendar"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/peak_scores"))
    args = parser.parse_args()
    models = {"ridge": args.ridge_dir, "xgboost": args.xgboost_dir}
    report = {"target": "load", "test_period_scored": False, "sites": {}}
    lines = ["# Daily peak error (validation)", "",
             "Peak error = forecast daily maximum - actual daily maximum, complete days only.", ""]
    for site, period in SITES.items():
        result = score_site(read_predictions(args.baseline_dir, models, site))
        report["sites"][site] = {"validation_period": period, **result}
        unit = "kW" if site == "azm" else "W"
        any_method = next(iter(result["methods"].values()))
        lines += [f"## {site} ({period}): {any_method['complete_days']} complete days, "
                  f"{result['shared_hours']} shared hours", "",
                  f"| Method | nMAE | Largest hourly error ({unit}) | Daily peak error ({unit}) | "
                  "Under-forecast days | Peak hour off (h) |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for name, r in result["methods"].items():
            lines.append(f"| {name} | {r['nmae']:.1%} | {r['largest_hourly_error']:.0f} | {r['mean_absolute_peak_error']:.0f} | "
                         f"{r['under_forecast_days']} of {r['complete_days']} | {r['mean_peak_hour_offset']:.1f} |")
        lines.append("")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

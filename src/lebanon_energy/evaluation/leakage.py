"""Leakage check: no model input may use information from after the forecast issue time.

Two independent tests on the Azm feature table (net load, holiday-aware):

1. Timing: the latest reading behind every feature row finished at or
   before the midnight issue time of the day it forecasts.
2. Deletion: for every day, all readings from the issue time onward are
   deleted and the day's features are rebuilt. They must be identical, which
   proves the features cannot see the day being forecast or anything later.

The feature table is written out so it can be inspected. Weather is not in
the served feature set; the weather experiments use forecast weather only
and assert their own availability times (data/weather.py).
"""

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from ..data.calendar_days import load_public_holidays
from ..features.holidays import holiday_aware_features
from ..models.quantiles import signed_net_series
from ..models.ridge import load_inputs


def check(series, holidays, first_day, end_day):
    rows, timing_violations, deletion_violations, days = [], 0, 0, 0
    day = first_day
    while day < end_day:
        earlier_only = {stamp: value for stamp, value in series.items() if stamp < day}
        for hour in range(24):
            stamp = day + timedelta(hours=hour)
            features, available = holiday_aware_features(series, stamp, holidays)
            if features != holiday_aware_features(earlier_only, stamp, holidays)[0]:
                deletion_violations += 1
            if features is None:
                continue
            if available > day:
                timing_violations += 1
            rows.append({"timestamp_local": stamp.isoformat(), "issue_time_local": day.isoformat(),
                         "is_public_holiday": stamp.date() in holidays, **features,
                         "latest_input_available_at_local": available.isoformat(),
                         "target_net_kw": series.get(stamp)})
        days += 1
        day += timedelta(days=1)
    return rows, {"days_checked": days, "feature_rows": len(rows), "timing_violations": timing_violations,
                  "deletion_violations": deletion_violations,
                  "passed": timing_violations == 0 and deletion_violations == 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-dir", type=Path, default=Path("outputs/baselines_confirmed_azm"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/features"))
    args = parser.parse_args()
    _, groups, series, _ = load_inputs(args.baseline_dir)
    net = signed_net_series(series[("azm", "load")], series[("azm", "pv")])
    end_day = datetime.fromisoformat(groups[("azm", "load")]["validation_end_exclusive"])
    first_day = min(net).replace(hour=0) + timedelta(days=1)
    rows, report = check(net, set(load_public_holidays()), first_day, end_day)
    report.update({"run_time_utc": datetime.now(timezone.utc).isoformat(), "site_id": "azm",
                   "first_day": first_day.isoformat(), "end_exclusive": end_day.isoformat(),
                   "feature_set": "hour of week (holiday = Sunday), 24 h and 168 h lags (holiday-aware), "
                                  "yesterday-was-holiday flag"})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys(key for row in rows for key in row))
    with (args.output_dir / "azm_feature_table.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "leakage_check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit("Leakage check FAILED")


if __name__ == "__main__":
    main()

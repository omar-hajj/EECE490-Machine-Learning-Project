"""Hour-by-hour backtest table for the operator page (Backtest page, Failure gallery).

Joins the logged rolling-origin forecasts with the generator rule: for each
hour, the configuration the rule would have picked from the upper estimate
(with the reserve margin and the minimum-run hold) and the configuration
the actual load needed. Nothing is refitted here. September is not read.
"""

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path

from ..generators.policy import Generator, hold_short_dips, recommend
from .error_analysis import BASELINE, POINT, UPPER


def build(predictions_csv, policy):
    generators = [Generator(item["generator_id"], float(item["usable_capacity_kw"])) for item in policy["generators"]]
    allowed, reserve = policy["allowed_configurations"], float(policy["reserve_margin_fraction"])
    label = {}
    for configuration in allowed:
        capacity = math.fsum(g.usable_capacity_kw for g in generators if g.generator_id in configuration)
        label.setdefault(capacity, []).append("+".join(sorted(configuration)))
    label = {capacity: " or ".join(names) for capacity, names in label.items()}

    def capacity_for(value, margin):
        if value is None:
            return None
        return recommend(max(value, 0.0), generators, allowed_configurations=allowed,
                         reserve_margin_fraction=margin)["selected_capacity_kw"]

    days = {}
    with Path(predictions_csv).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            stamp = datetime.fromisoformat(row["timestamp_local"])
            values = {name: float(row[name]) if row[name] != "" else None for name in ("actual", POINT, UPPER, BASELINE)}
            days.setdefault(stamp.date(), []).append((stamp, values))
    rows = []
    for day in sorted(days):
        hours = sorted(days[day])
        picked = hold_short_dips([capacity_for(values[UPPER], reserve) for _, values in hours],
                                 int(policy.get("minimum_run_hours", 1)))
        for (stamp, values), capacity in zip(hours, picked):
            needed = capacity_for(values["actual"], 0.0)
            verdict = ""
            if capacity is not None and values["actual"] is not None:
                verdict = ("undersized" if needed is None or capacity < max(values["actual"], 0.0)
                           else "oversized" if capacity > needed else "right-sized")
            rows.append({"timestamp_local": stamp.isoformat(), "actual_kw": values["actual"],
                         "forecast_kw": values[POINT], "upper_kw": values[UPPER], "baseline_kw": values[BASELINE],
                         "picked_capacity_kw": capacity, "picked": label.get(capacity, ""),
                         "needed_capacity_kw": needed, "needed": label.get(needed, ""), "verdict": verdict})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--predictions", type=Path, default=Path("outputs/walk_forward/predictions.csv"))
    parser.add_argument("--policy", type=Path, default=Path("config/azm_generators.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/walk_forward/backtest.csv"))
    args = parser.parse_args()
    rows = build(args.predictions, json.loads(args.policy.read_text(encoding="utf-8")))
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    verdicts = [row["verdict"] for row in rows if row["verdict"]]
    print(f"Wrote {args.output}: {len(rows)} hours; " + ", ".join(
        f"{name} {verdicts.count(name)}" for name in ("right-sized", "oversized", "undersized")))


if __name__ == "__main__":
    main()

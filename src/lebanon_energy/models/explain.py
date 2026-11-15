"""Exact explanations of the served Ridge forecast.

Ridge is linear, so a forecast splits exactly into the training-average
level plus one contribution per input:

    forecast = average + sum over inputs of coefficient x (value - training mean) / training spread

No approximation (such as SHAP sampling) is needed; the contributions add
up to the forecast to rounding error. The 168 hour-of-week columns are
reported together as one "time of week" driver.
"""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path

GROUPS = {"lag_168h": "same hour last week", "lag_24h": "same hour yesterday",
          "lag_24h_is_holiday": "yesterday was a holiday", "hour_of_week": "time of week"}


def contributions(pipeline, features):
    """Return (training-average level, {group: kW contribution}) for one feature row."""
    vectorizer, scaler, ridge = (pipeline.named_steps[name] for name in ("vectorizer", "scaler", "ridge"))
    values = vectorizer.transform([features])[0]
    parts = {}
    for name, value, mean, scale, coefficient in zip(vectorizer.get_feature_names_out(), values, scaler.mean_,
                                                     scaler.scale_, ridge.coef_):
        group = name.split("=")[0]
        parts[group] = parts.get(group, 0.0) + float(coefficient * (value - mean) / scale)
    return float(ridge.intercept_), parts


def describe(features, parts, stamp, limit=3, holiday=False):
    """The `limit` largest drivers as sentences an operator can read.

    On a public holiday the two lags are the same hour on the last two
    Sundays (features/holidays.py), and the sentences say so.
    """
    sources = ({"lag_24h": "on the most recent Sunday", "lag_168h": "on the Sunday before that"} if holiday
               else {"lag_24h": "yesterday", "lag_168h": "last week"})
    drivers = []
    for group, value in sorted(parts.items(), key=lambda item: -abs(item[1])):
        if len(drivers) == limit:
            break
        if abs(value) < 0.5 or (group == "lag_24h_is_holiday" and not features.get(group)):
            continue
        if group == "hour_of_week":
            when = "A holiday (treated as a Sunday)" if holiday else stamp.strftime("%A")
            text = f"{when} at {stamp.strftime('%H:%M')} is usually " + (
                "busier" if value > 0 else "quieter") + " than the average hour"
        elif group in sources:
            text = f"At the same hour {sources[group]} the load was {features[group]:.0f} kW"
        else:
            text = "Yesterday was a holiday, so yesterday's reading counts for less"
        drivers.append({"input": group, "label": GROUPS.get(group, group), "effect_kw": value, "text": text})
    return drivers


def global_importance(pipeline, rows):
    """Mean absolute contribution per input over `rows` of (timestamp, features)."""
    totals, count = {}, 0
    for _, features in rows:
        _, parts = contributions(pipeline, features)
        for group, value in parts.items():
            totals[group] = totals.get(group, 0.0) + abs(value)
        count += 1
    return {GROUPS.get(group, group): total / count for group, total in sorted(totals.items(), key=lambda i: -i[1])}


def main():
    import joblib

    from ..features.holidays import holiday_aware_features
    from .quantiles import signed_net_series
    from .ridge import load_inputs

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-dir", type=Path, default=Path("outputs/baselines_confirmed_azm"))
    parser.add_argument("--bundle", type=Path, default=Path("outputs/serving/azm_bundle.joblib"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/explainability"))
    args = parser.parse_args()
    bundle = joblib.load(args.bundle)
    _, _, series, _ = load_inputs(args.baseline_dir)
    net = signed_net_series(series[("azm", "load")], series[("azm", "pv")])
    holidays, model = set(bundle["holidays"]), bundle["models"]["net"]
    rows = []
    for stamp in sorted(net):
        features, _ = holiday_aware_features(net, stamp, holidays)
        if features is not None:
            rows.append((stamp, features))
    # The daily peak hour is where a wrong forecast picks the wrong generator.
    by_day = {}
    for stamp, features in rows:
        if stamp.date() not in by_day or net[stamp] > net[by_day[stamp.date()][0]]:
            by_day[stamp.date()] = (stamp, features)
    vectorizer, scaler, ridge = (model.named_steps[name] for name in ("vectorizer", "scaler", "ridge"))
    names = list(vectorizer.get_feature_names_out())
    per_unit = {name: float(ridge.coef_[names.index(name)] / scaler.scale_[names.index(name)])
                for name in ("lag_24h", "lag_168h")}
    worked = max(by_day.values(), key=lambda item: net[item[0]])
    level, parts = contributions(model, worked[1])
    report = {"run_time_utc": datetime.now(timezone.utc).isoformat(), "site_id": "azm",
              "model": "holiday-aware Ridge on net load", "rows": len(rows),
              "training_end_exclusive": bundle["training_end_exclusive"].isoformat(),
              "average_level_kw": level,
              "kw_per_kw_of_input": per_unit,
              "mean_absolute_contribution_kw": {"all_hours": global_importance(model, rows),
                                                "daily_peak_hours": global_importance(model, list(by_day.values()))},
              "worked_example": {"timestamp_local": worked[0].isoformat(), "actual_kw": net[worked[0]],
                                 "forecast_kw": level + math.fsum(parts.values()), "average_level_kw": level,
                                 "drivers": describe(worked[1], parts, worked[0], limit=4)},
              "test_period_scored": False}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

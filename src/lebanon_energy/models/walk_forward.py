"""Daily rolling-origin check of Azm net-load forecasts and upper estimates.

Every day from the first usable origin to the end of validation is forecast
at midnight by models fitted only on hours before that midnight. This is the
roadmap's "rolling-origin backtest" and it mirrors how the service would be
run (refit each night). Net load = campus load - PV, the power the generators
must supply. Hyperparameters are fixed in advance (config/walk_forward.json),
so no day is used to tune the model that forecasts it. September is never read.

Point methods answer "how big is the error"; upper methods answer "is the
estimate high enough to size a generator on". Upper methods are compared on
coverage (share of hours at or below the estimate, target 90%) and on
wrong-generator hours.
"""

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path

from ..data.calendar_days import load_public_holidays
from ..data.preparation import file_sha256
from ..evaluation.metrics import score
from ..features.history import history_calendar_features
from ..features.holidays import holiday_aware_features
from ..generators.policy import choice_errors, load_policy
from .baselines import fit_weekday_profile, predict
from .quantiles import quantile_scores, signed_net_series
from .ridge import load_inputs, make_pipeline

POINT_METHODS = ("last_week", "weekday_average", "ridge", "ridge_holiday", "xgboost", "xgboost_change")
WEATHER_METHOD = "ridge_holiday_weather"  # scored only when aligned forecast weather is supplied
UPPER_METHODS = ("weekday_p90", "xgboost_p90", "xgboost_p90_change", "ridge_plus_recent_errors",
                 "ridge_holiday_plus_recent_errors")


def upper_rank_value(values, quantile):
    """Finite-sample upper order statistic: the ceil((n+1)q)-th smallest value.

    With few values the rank can exceed n; the largest value is used then.
    Residuals of a time series are dependent, so this is an empirical margin,
    not a coverage guarantee.
    """
    ordered = sorted(float(value) for value in values)
    if not ordered or not all(math.isfinite(value) for value in ordered) or not 0 < quantile < 1:
        raise ValueError("Finite values and a quantile between zero and one are required")
    return ordered[min(math.ceil((len(ordered) + 1) * quantile), len(ordered)) - 1]


def recent_error_margin(residuals, issue_time, hour, *, quantile, window_days, minimum_days):
    """kW to add to a point forecast for `hour`, from errors on recent days.

    residuals maps past target hours to (actual - forecast). Only days in the
    `window_days` before the issue time are used, so every error was known at
    midnight. Errors from the same clock hour are used; None is returned when
    fewer than `minimum_days` of them exist.
    """
    values = []
    for back in range(1, window_days + 1):
        value = residuals.get(issue_time - timedelta(days=back) + timedelta(hours=hour))
        if value is not None:
            values.append(value)
    if len(values) < minimum_days:
        return None
    return upper_rank_value(values, quantile)


class ChangeFromLastWeek:
    """Fit a model on (value - same hour last week) and add last week back.

    Trees cannot predict above the largest target they were trained on. The
    weekly change stays in a familiar range even when the level rises, as it
    does in September.
    """

    def __init__(self, model):
        self.model = model

    def fit(self, rows, targets):
        self.model.fit(rows, [target - row["lag_168h"] for row, target in zip(rows, targets)])
        return self

    def predict(self, rows):
        return [float(change) + row["lag_168h"] for row, change in zip(rows, self.model.predict(rows))]


def boosted(parameters, quantile=None):
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.pipeline import Pipeline
    from xgboost import XGBRegressor

    objective = dict(objective="reg:squarederror") if quantile is None else dict(
        objective="reg:quantileerror", quantile_alpha=quantile)
    return Pipeline([("vectorizer", DictVectorizer(sparse=False)),
                     ("boosting", XGBRegressor(tree_method="hist", n_jobs=1, random_state=42,
                                               min_child_weight=5, reg_lambda=1, **objective, **parameters))])


def weekday_quantile_profile(series, training_end, quantile):
    groups = {}
    for timestamp, value in series.items():
        if timestamp < training_end:
            groups.setdefault((timestamp.weekday(), timestamp.hour), []).append(value)
    return {key: upper_rank_value(values, quantile) for key, values in groups.items()}


def read_weather(path):
    """{timestamp: forecast-weather features} from scripts/prepare_weather_features.py output."""
    from ..data.weather import VARIABLES
    weather = {}
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            stamp = datetime.fromisoformat(row["timestamp_local"])
            if datetime.fromisoformat(row["nominal_available_at_local"]) > stamp.replace(hour=0):
                raise ValueError("Weather forecast would not be available at the midnight issue time")
            weather[stamp] = {name: float(row[name]) for name in VARIABLES}
    return weather


def run(net, holidays, configuration, first_day, end_day, progress=None, weather=None):
    """Return {timestamp: {"actual": value or None, method: forecast or None}}."""
    quantile = configuration["quantile"]
    builders = {"plain": lambda stamp: history_calendar_features(net, stamp),
                "holiday": lambda stamp: holiday_aware_features(net, stamp, holidays)}
    if weather is not None:
        def with_weather(stamp):
            values, available = holiday_aware_features(net, stamp, holidays)
            if values is None or stamp not in weather:
                return None, None
            return {**values, **weather[stamp]}, available
        builders["weather"] = with_weather
    first_hour = min(net)
    features = {name: {} for name in builders}
    stamp = first_hour.replace(hour=0) + timedelta(days=8)
    while stamp < end_day:
        for name, builder in builders.items():
            features[name][stamp] = builder(stamp)[0]
        stamp += timedelta(hours=1)
    table, residuals = {}, {"ridge": {}, "ridge_holiday": {}}
    day = first_day
    while day < end_day:
        hours = [day + timedelta(hours=hour) for hour in range(24)]
        training = {name: [(values, net[stamp]) for stamp, values in rows.items()
                           if stamp < day and values is not None and stamp in net]
                    for name, rows in features.items()}
        if len(training["plain"]) < configuration["minimum_training_rows"]:
            raise ValueError("Too little history before the first origin")
        models = {}
        candidates = {WEATHER_METHOD: ("weather", lambda: make_pipeline(configuration["ridge_alpha"]))} if weather is not None else {}
        for method, (variant, factory) in {**candidates, **{
                "ridge": ("plain", lambda: make_pipeline(configuration["ridge_alpha"])),
                "ridge_holiday": ("holiday", lambda: make_pipeline(configuration["ridge_alpha"])),
                "xgboost": ("plain", lambda: boosted(configuration["xgboost"])),
                "xgboost_change": ("plain", lambda: ChangeFromLastWeek(boosted(configuration["xgboost"]))),
                "xgboost_p90": ("plain", lambda: boosted(configuration["xgboost_quantile"], quantile)),
                "xgboost_p90_change": ("plain", lambda: ChangeFromLastWeek(
                    boosted(configuration["xgboost_quantile"], quantile)))}}.items():
            rows, targets = zip(*training[variant])
            models[method] = (variant, factory().fit(list(rows), list(targets)))
        profile = fit_weekday_profile(net, day)
        upper_profile = weekday_quantile_profile(net, day, quantile)
        for stamp in hours:
            entry = {"actual": net.get(stamp)}
            for method in ("last_week", "weekday_average"):
                result = predict(net, profile, stamp, method)
                entry[method] = result[0] if result else None
            entry["weekday_p90"] = upper_profile.get((stamp.weekday(), stamp.hour))
            for method, (variant, model) in models.items():
                row = features[variant].get(stamp)
                entry[method] = float(model.predict([row])[0]) if row is not None else None
            for method in ("ridge", "ridge_holiday"):
                margin = recent_error_margin(residuals[method], day, stamp.hour, quantile=quantile,
                                             window_days=configuration["recent_error_window_days"],
                                             minimum_days=configuration["recent_error_minimum_days"])
                entry[f"{method}_plus_recent_errors"] = (
                    entry[method] + margin if entry[method] is not None and margin is not None else None)
            table[stamp] = entry
        # Yesterday's errors become known only now, after the day has been forecast.
        for stamp in hours:
            for method in residuals:
                if table[stamp]["actual"] is not None and table[stamp][method] is not None:
                    residuals[method][stamp] = table[stamp]["actual"] - table[stamp][method]
        if progress:
            progress(day)
        day += timedelta(days=1)
    return table


def summarize(table, policy, quantile, periods):
    generators, allowed, margin = policy
    methods = POINT_METHODS + UPPER_METHODS
    if any(WEATHER_METHOD in entry for entry in table.values()):
        methods = POINT_METHODS + (WEATHER_METHOD,) + UPPER_METHODS
    common = sorted(stamp for stamp, entry in table.items()
                    if entry["actual"] is not None and all(entry[method] is not None for method in methods))
    report = {"common_hours": len(common), "first_common_hour": common[0].isoformat(),
              "last_common_hour": common[-1].isoformat(), "periods": {}}
    for label, (start, end) in periods.items():
        hours = [stamp for stamp in common if start <= stamp < end]
        if not hours:
            continue
        actual = [table[stamp]["actual"] for stamp in hours]
        section = {"hours": len(hours), "mean_actual_net_kw": math.fsum(actual) / len(actual),
                   "maximum_actual_net_kw": max(actual), "point": {}, "upper": {}}
        for method in methods:
            forecast = [table[stamp][method] for stamp in hours]
            choice = choice_errors(actual, forecast, generators, allowed_configurations=allowed,
                                   reserve_margin_fraction=margin)
            kind = "upper" if method in UPPER_METHODS else "point"
            entry = {"generator_choice": choice}
            if kind == "point":
                # Net load can be negative (PV surplus), so MAE is divided by the mean of |actual|.
                errors = [abs(a - f) for a, f in zip(actual, forecast)]
                entry["mae_kw"] = math.fsum(errors) / len(errors)
                entry["nmae"] = entry["mae_kw"] / (math.fsum(abs(a) for a in actual) / len(actual))
                entry["largest_error_kw"] = max(errors)
            entry["quantile_scores"] = quantile_scores(actual, forecast, quantile)
            section[kind][method] = entry
        report["periods"][label] = section
    return report


def operator_practice(table, hourly_generators_csv, policy, method):
    """Compare what the operator actually ran with what `method` would have picked.

    Only hours where one configuration ran unchanged are used. This is the
    inferred current practice (see GENERATORS.md), not a confirmed procedure.
    """
    generators, allowed, margin = policy
    capacity = {item.generator_id: item.usable_capacity_kw for item in generators}
    actual, forecast, ran = [], [], []
    with Path(hourly_generators_csv).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            stamp = datetime.fromisoformat(row["timestamp_local"])
            entry = table.get(stamp)
            if row["configuration"] in ("mixed", "") or entry is None:
                continue
            if entry["actual"] is None or entry.get(method) is None:
                continue
            actual.append(entry["actual"])
            forecast.append(entry[method])
            ran.append(math.fsum(capacity[unit] for unit in row["configuration"].split("+")))
    if not actual:
        return None
    from ..generators.policy import recommend
    counts = {"undersized_hours": 0, "oversized_hours": 0, "right_sized_hours": 0}
    excess = 0.0
    for truth, running in zip(actual, ran):
        needed = recommend(max(truth, 0.0), generators, allowed_configurations=allowed,
                           reserve_margin_fraction=0.0)["selected_capacity_kw"]
        if needed is None or running < truth:
            counts["undersized_hours"] += 1
        elif running > needed:
            counts["oversized_hours"] += 1
            excess += running - needed
        else:
            counts["right_sized_hours"] += 1
    return {"hours": len(actual), "method": method,
            "operator_actual": {**counts, "excess_capacity_kwh": excess},
            "forecast_rule": choice_errors(actual, forecast, generators, allowed_configurations=allowed,
                                           reserve_margin_fraction=margin)}


def _percent(part, whole):
    return f"{part} ({part / whole:.1%})"


def summary_markdown(report):
    lines = ["# Azm rolling-origin results (net load)", "",
             f"Each day is forecast at midnight by models refitted on earlier hours only. "
             f"{report['summary']['common_hours']} hours shared by every method, "
             f"{report['summary']['first_common_hour'][:10]} to {report['summary']['last_common_hour'][:10]}. "
             "September is not read.", ""]
    for label, section in report["summary"]["periods"].items():
        lines += [f"## {label} ({section['hours']} hours, mean net load {section['mean_actual_net_kw']:.0f} kW, "
                  f"highest {section['maximum_actual_net_kw']:.0f} kW)", "",
                  "| Point forecast | nMAE | Largest error (kW) | Undersized hours | Oversized hours |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for method, entry in section["point"].items():
            choice = entry["generator_choice"]
            lines.append(f"| {method} | {entry['nmae']:.1%} | {entry['largest_error_kw']:.0f} | "
                         f"{_percent(choice['undersized_hours'], section['hours'])} | "
                         f"{_percent(choice['oversized_hours'], section['hours'])} |")
        lines += ["", "| Upper estimate (target 90%) | Coverage | Pinball loss | Undersized hours | Oversized hours |",
                  "| --- | ---: | ---: | ---: | ---: |"]
        for method, entry in section["upper"].items():
            choice, scores = entry["generator_choice"], entry["quantile_scores"]
            lines.append(f"| {method} | {scores['empirical_hourly_coverage']:.1%} | {scores['pinball_loss']:.2f} | "
                         f"{_percent(choice['undersized_hours'], section['hours'])} | "
                         f"{_percent(choice['oversized_hours'], section['hours'])} |")
        lines.append("")
    practice = report.get("operator_practice")
    if practice:
        ran, rule = practice["operator_actual"], practice["forecast_rule"]
        lines += ["## Inferred current practice vs. the forecast rule", "",
                  f"{practice['hours']} hours where one configuration ran unchanged. Rule uses `{practice['method']}`.", "",
                  "| | Undersized hours | Oversized hours | Right-sized | Excess capacity (kWh) |",
                  "| --- | ---: | ---: | ---: | ---: |",
                  f"| What the operator ran | {_percent(ran['undersized_hours'], practice['hours'])} | "
                  f"{_percent(ran['oversized_hours'], practice['hours'])} | "
                  f"{_percent(ran['right_sized_hours'], practice['hours'])} | {ran['excess_capacity_kwh']:,.0f} |",
                  f"| Forecast rule | {_percent(rule['undersized_hours'], practice['hours'])} | "
                  f"{_percent(rule['oversized_hours'], practice['hours'])} | "
                  f"{_percent(rule['right_sized_hours'], practice['hours'])} | {rule['excess_capacity_kwh']:,.0f} |", ""]
    return "\n".join(lines)


def main():
    from threadpoolctl import threadpool_limits

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline-dir", type=Path, default=Path("outputs/baselines_confirmed_azm"))
    parser.add_argument("--config", type=Path, default=Path("config/walk_forward.json"))
    parser.add_argument("--policy", type=Path, default=Path("config/azm_generators.json"))
    parser.add_argument("--hourly-generators", type=Path, default=Path("outputs/generators/azm_hourly_generators.csv"))
    parser.add_argument("--weather-features", type=Path, default=Path("outputs/weather_features/features.csv"),
                        help="Aligned forecast weather; the weather method is skipped when the file is absent")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/walk_forward"))
    args = parser.parse_args()
    configuration = json.loads(args.config.read_text(encoding="utf-8"))
    source, groups, series, _ = load_inputs(args.baseline_dir)
    net = signed_net_series(series[("azm", "load")], series[("azm", "pv")])
    end_day = datetime.fromisoformat(groups[("azm", "load")]["validation_end_exclusive"])
    validation_start = datetime.fromisoformat(groups[("azm", "load")]["validation_start"])
    first_day = datetime.fromisoformat(configuration["first_origin"])
    holidays = set(load_public_holidays())
    policy = load_policy(args.policy)
    weather = read_weather(args.weather_features) if args.weather_features.is_file() else None
    with threadpool_limits(limits=1):
        table = run(net, holidays, configuration, first_day, end_day, weather=weather,
                    progress=lambda day: print(f"Forecast {day.date()}", flush=True) if day.day == 1 else None)
    periods = {"All months": (first_day, end_day)}
    month = first_day
    while month < end_day:
        following = (month.replace(day=1) + timedelta(days=32)).replace(day=1)
        label = month.strftime("%B") + (" (validation)" if month >= validation_start else "")
        periods[label] = (month, following)
        month = following
    report = {"run_time_utc": datetime.now(timezone.utc).isoformat(), "site_id": "azm",
              "target": "signed_net_load_kw = campus_load_kw - solar_pv_kw", "configuration": configuration,
              "first_origin": first_day.isoformat(), "end_exclusive": end_day.isoformat(),
              "test_period_scored": False, "source_sha256": source["source_sha256"],
              "input_sha256": file_sha256(args.baseline_dir / "hourly_data.csv"),
              "policy_sha256": file_sha256(args.policy), "code_sha256": file_sha256(Path(__file__)),
              "reserve_margin_fraction": policy[2], "forecast_weather_method_scored": weather is not None,
              "summary": summarize(table, policy, configuration["quantile"], periods)}
    if args.hourly_generators.is_file():
        report["operator_practice"] = operator_practice(table, args.hourly_generators, policy,
                                                        configuration["served_upper_method"])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    (args.output_dir / "summary.md").write_text(summary_markdown(report), encoding="utf-8")
    columns = ["timestamp_local", "issue_time_local", "actual", *POINT_METHODS,
               *([WEATHER_METHOD] if weather is not None else []), *UPPER_METHODS]
    with (args.output_dir / "predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for stamp, entry in sorted(table.items()):
            writer.writerow({"timestamp_local": stamp.isoformat(), "issue_time_local": stamp.replace(hour=0).isoformat(),
                             **{name: entry.get(name) for name in columns[2:]}})
    from ..evaluation import run_log
    logged = []
    for label, section in report["summary"]["periods"].items():
        for kind in ("point", "upper"):
            for method, entry in section[kind].items():
                metrics = {"undersized_hours": entry["generator_choice"]["undersized_hours"],
                           "oversized_hours": entry["generator_choice"]["oversized_hours"]}
                if kind == "point":
                    metrics["nmae"] = entry["nmae"]
                else:
                    metrics["coverage"] = entry["quantile_scores"]["empirical_hourly_coverage"]
                logged += [{"run_time_utc": report["run_time_utc"], "script": "walk_forward_azm", "site_id": "azm",
                            "split": label, "method": method, "metric": metric, "value": value,
                            "hours": section["hours"], "identifier_sha256": report["code_sha256"][:12]}
                           for metric, value in metrics.items()]
    run_log.append(logged)
    print(summary_markdown(report))


if __name__ == "__main__":
    main()

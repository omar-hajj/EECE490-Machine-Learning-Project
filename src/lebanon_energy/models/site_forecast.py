"""Day-ahead forecast for a site the service has never seen, from its uploaded history.

Same method as the Azm service (holiday-aware Ridge on net load, plus a
margin from the forecast's own recent errors), fitted on the fly:

  1. the last days of the history are forecast one by one, each by a model
     fitted on earlier hours only, to measure how the method does at this
     site and to collect the errors the safety margin is built from;
  2. the requested day is forecast by a model fitted on all the history.

Nothing here has been tested on held-out data for the new site: the score
returned with the forecast is the only evidence, and it comes from the
site's own history. A site needs at least MINIMUM_DAYS days of hourly data.
"""

from datetime import timedelta
import math

from ..generators.policy import Generator, hold_short_dips, recommend
from .baselines import fit_weekday_profile, predict
from .tuning import build_matrix, linear_model, rolling_predictions
from .walk_forward import recent_error_margin, upper_rank_value

MINIMUM_DAYS, FULL_CONFIDENCE_DAYS = 14, 35


def all_combinations(names):
    """Every non-empty set of units (used when units may run in parallel)."""
    sets = [[]]
    for name in names:
        sets += [existing + [name] for existing in sets]
    return [units for units in sets if units]


def forecast_site(series, issue, holidays, generators=(), *, allow_parallel=False, reserve_margin_fraction=0.1,
                  minimum_run_hours=3, quantile=0.9, window_days=28, alpha=1.0):
    """series: {naive hourly timestamp: net load in kW}, all before `issue` (a midnight)."""
    history = {stamp: value for stamp, value in series.items() if stamp < issue}
    if not history:
        raise ValueError("No readings before the day to forecast")
    days = len({stamp.date() for stamp in history})
    if days < MINIMUM_DAYS or len(history) < MINIMUM_DAYS * 20:
        raise ValueError(f"At least {MINIMUM_DAYS} days of hourly history are needed; {days} days "
                         f"({len(history)} hours) were supplied")
    end = issue + timedelta(days=1)
    start = min(history).replace(hour=0) + timedelta(days=8)
    stamps, matrix, targets = build_matrix(history, holidays, (), start, end)
    first_rolled = max(issue - timedelta(days=window_days), start + timedelta(days=5))
    predictions = rolling_predictions(stamps, matrix, targets, first_rolled, end, linear_model("ridge", alpha))
    residuals = {stamp: history[stamp] - value for stamp, value in predictions.items() if stamp in history}
    profile = fit_weekday_profile(history, issue)

    def fallback(stamp):
        for method in ("last_week", "weekday_average"):
            result = predict(history, profile, stamp, method)
            if result is not None:
                return result[0], method
        return None, "unavailable"

    # Errors of the fallbacks over the same recent days, pooled: their margins cannot be per hour.
    fallback_errors = {"last_week": [], "weekday_average": []}
    for stamp, value in history.items():
        if stamp < first_rolled:
            continue
        earlier = history.get(stamp - timedelta(hours=168))
        if earlier is not None:
            fallback_errors["last_week"].append(value - earlier)
        # The weekday average includes this hour itself, so this margin is slightly optimistic.
        typical = profile.get((stamp.weekday(), stamp.hour))
        if typical is not None:
            fallback_errors["weekday_average"].append(value - typical[0])
    pooled = upper_rank_value(residuals.values(), quantile) if residuals else None

    units = [Generator(item["generator_id"], float(item["usable_capacity_kw"])) for item in generators]
    allowed = all_combinations([unit.generator_id for unit in units]) if allow_parallel else [[u.generator_id] for u in units]
    hourly, methods = [], []
    for hour in range(24):
        stamp = issue + timedelta(hours=hour)
        if stamp in predictions:
            value, method = predictions[stamp], "ridge"
            margin = recent_error_margin(residuals, issue, hour, quantile=quantile, window_days=window_days, minimum_days=7)
            basis = "recent_errors"
            if margin is None:
                margin, basis = pooled, "pooled_errors"
        else:
            value, method = fallback(stamp)
            errors = fallback_errors.get(method) or []
            margin = max(upper_rank_value(errors, quantile), 0.0) if errors else None
            basis = "pooled_errors" if margin is not None else None
        upper = value + margin if value is not None and margin is not None else None
        advice = {"status": "unavailable", "configurations": [], "capacity_kw": None, "required_capacity_kw": None}
        if upper is not None and units:
            choice = recommend(max(upper, 0.0), units, allowed_configurations=allowed,
                               reserve_margin_fraction=reserve_margin_fraction)
            advice = {"status": choice["status"], "configurations": choice["candidate_configurations"],
                      "capacity_kw": choice["selected_capacity_kw"], "required_capacity_kw": choice["required_capacity_kw"]}
        methods.append(method)
        hourly.append({"timestamp_local": stamp.isoformat(), "net_kw": value, "net_upper_kw": upper, "net_method": method,
                       "margin_kw": margin, "margin_basis": basis, "generator": advice})
    if units:
        by_capacity = {}
        for configuration in allowed:
            capacity = math.fsum(unit.usable_capacity_kw for unit in units if unit.generator_id in configuration)
            by_capacity.setdefault(capacity, []).append(sorted(configuration))
        held = hold_short_dips([row["generator"]["capacity_kw"] for row in hourly], int(minimum_run_hours))
        for row, capacity in zip(hourly, held):
            if capacity != row["generator"]["capacity_kw"]:
                row["generator"].update(capacity_kw=capacity, configurations=by_capacity[capacity])

    scored = sorted(stamp for stamp in residuals if stamp - timedelta(hours=168) in history)
    check = None
    if scored:
        actual = [history[s] for s in scored]
        level = math.fsum(abs(a) for a in actual) / len(actual)
        mae = math.fsum(abs(residuals[s]) for s in scored) / len(scored)
        baseline = math.fsum(abs(history[s] - history[s - timedelta(hours=168)]) for s in scored) / len(scored)
        covered = [(s, recent_error_margin(residuals, s.replace(hour=0), s.hour, quantile=quantile,
                                           window_days=window_days, minimum_days=7)) for s in scored]
        covered = [(s, m) for s, m in covered if m is not None]
        check = {"days": len({s.date() for s in scored}), "hours": len(scored), "mae_kw": mae,
                 "nmae": mae / level if level else None, "baseline_mae_kw": baseline,
                 "baseline_nmae": baseline / level if level else None,
                 "upper_coverage": (sum(history[s] <= predictions[s] + m for s, m in covered) / len(covered)) if covered else None,
                 "coverage_hours": len(covered)}

    unavailable, fallbacks = methods.count("unavailable"), 24 - methods.count("ridge") - methods.count("unavailable")
    notes = []
    if unavailable:
        level_name = "unavailable"
        notes.append(f"No forecast for {unavailable} of 24 hours: the history has gaps where the model needs it.")
    elif fallbacks:
        level_name = "fallback"
        notes.append(f"{fallbacks} of 24 hours use a simpler fallback because recent readings are missing.")
    else:
        level_name = "full"
        notes.append("Every hour uses the main model.")
    if days < FULL_CONFIDENCE_DAYS:
        level_name = "fallback" if level_name == "full" else level_name
        notes.append(f"Only {days} days of history: the safety margin rests on few days. {FULL_CONFIDENCE_DAYS} or more is better.")
    if not units:
        notes.append("No generators were given, so there is no generator plan.")
    policy = None
    if units:
        policy = {"status": "entered_by_user", "reserve_margin_fraction": reserve_margin_fraction,
                  "minimum_run_hours": int(minimum_run_hours),
                  "rule": "Run the smallest allowed configuration whose capacity covers the upper estimate times (1 + reserve margin).",
                  "capacities_kw": {unit.generator_id: unit.usable_capacity_kw for unit in units},
                  "allowed_configurations": allowed}
    return {"issue_time_local": issue.isoformat(), "units": "kW", "history_days": days, "history_hours": len(history),
            "history_first": min(history).isoformat(), "history_last": max(history).isoformat(),
            "input_status": {"level": level_name, "message": " ".join(notes)}, "history_check": check,
            "generator_policy": policy, "hourly": hourly,
            "limitations": ["Fitted on the uploaded history only; not tested on held-out data for this site.",
                            "The upper estimate is empirical (about 9 hours in 10), not a guarantee.",
                            "Hourly averages: peaks inside an hour and switching limits are not modelled.",
                            "The operator keeps the final decision."]}

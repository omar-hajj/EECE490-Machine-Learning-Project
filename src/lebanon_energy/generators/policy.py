"""Capacity planning with explicit equipment and operating policy inputs.

This module does not itself infer ratings or choose a reserve margin; the
draft Azm inputs come from generator_capacity.py (observed maxima) and are
supplied explicitly. An hourly recommendation does not certify instantaneous
overload protection, fuel optimality, switching feasibility, or electrical
protection.
"""

from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class Generator:
    generator_id: str
    usable_capacity_kw: float
    available: bool = True


def recommend(
    net_load_upper_kw: float, generators: Iterable[Generator], *,
    allowed_configurations: Iterable[Iterable[str]], reserve_margin_fraction: float,
) -> dict:
    """Choose a permitted configuration with the smallest sufficient capacity.

    Supply a validated upper estimate of net load. Subtracting the P90 solar
    prediction from P90 demand does not in general produce P90 net demand.
    Allowed combinations and a reserve margin are required inputs. Tied
    configurations are returned together for the operator to choose between.
    Include an empty configuration explicitly to permit all generators off.
    """
    if not math.isfinite(net_load_upper_kw) or net_load_upper_kw < 0:
        raise ValueError("Net load upper estimate must be finite and nonnegative")
    if not math.isfinite(reserve_margin_fraction) or reserve_margin_fraction < 0:
        raise ValueError("Reserve margin must be finite and nonnegative")
    equipment = list(generators)
    by_id = {item.generator_id: item for item in equipment}
    if len(by_id) != len(equipment):
        raise ValueError("Generator identifiers must be unique")
    for item in equipment:
        if not item.generator_id or not math.isfinite(item.usable_capacity_kw) or item.usable_capacity_kw <= 0:
            raise ValueError("Every generator needs an identifier and positive finite usable capacity")
    configurations = [tuple(configuration) for configuration in allowed_configurations]
    if not configurations:
        raise ValueError("Explicit permitted generator configurations are required")
    feasible = []
    required_kw = net_load_upper_kw * (1 + reserve_margin_fraction)
    if not math.isfinite(required_kw):
        raise ValueError("Required capacity is not finite")
    for configuration in configurations:
        if len(set(configuration)) != len(configuration):
            raise ValueError("A configuration cannot repeat the same generator")
        if any(identifier not in by_id for identifier in configuration):
            raise ValueError("Configuration references an unknown generator")
        if any(not by_id[identifier].available for identifier in configuration):
            continue
        capacity = math.fsum(by_id[identifier].usable_capacity_kw for identifier in configuration)
        if capacity >= required_kw:
            feasible.append((capacity, configuration))
    if not feasible:
        return {"status": "insufficient_available_capacity", "required_capacity_kw": required_kw,
                "candidate_configurations": [], "selected_capacity_kw": None}
    smallest_capacity = min(capacity for capacity, _ in feasible)
    candidates = sorted({tuple(sorted(configuration)) for capacity, configuration in feasible if capacity == smallest_capacity})
    return {"status": "capacity_candidates_available", "required_capacity_kw": required_kw,
            "candidate_configurations": [list(item) for item in candidates],
            "selected_capacity_kw": smallest_capacity}


def load_policy(path):
    """Read a generator policy JSON (for example config/azm_generators.json)."""
    import json
    from pathlib import Path

    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    generators = [Generator(item["generator_id"], float(item["usable_capacity_kw"]), item.get("available", True))
                  for item in policy["generators"]]
    return generators, policy["allowed_configurations"], float(policy["reserve_margin_fraction"])


def choice_errors(actual_net_kw, forecast_net_kw, generators, *, allowed_configurations, reserve_margin_fraction):
    """Use-linked metric: hours where the forecast picks the wrong generator size.

    For each hour the forecast picks the smallest allowed configuration that
    covers forecast net load x (1 + reserve margin). The configuration that
    was actually needed is the smallest one covering the actual net load with
    no margin. The pick is:

    - undersized (overload risk) when its capacity is below the actual net load;
    - oversized (wasted fuel) when its capacity exceeds the needed capacity;
    - right-sized otherwise.

    Negative net values (PV surplus) are treated as zero demand on the
    generators. Hours whose actual or forecast need exceeds every allowed
    configuration are counted separately as infeasible.
    """
    actual, forecast = list(actual_net_kw), list(forecast_net_kw)
    if not actual or len(actual) != len(forecast):
        raise ValueError("Actual and forecast net load must be nonempty and equally long")
    if any(not math.isfinite(value) for value in actual + forecast):
        raise ValueError("Net load values must be finite")
    equipment = list(generators)
    configurations = [list(c) for c in allowed_configurations]
    picks = []
    for estimate in forecast:
        picks.append(recommend(max(estimate, 0.0), equipment, allowed_configurations=configurations,
                               reserve_margin_fraction=reserve_margin_fraction)["selected_capacity_kw"])
    return pick_errors(actual, picks, equipment, allowed_configurations=configurations)


def pick_errors(actual_net_kw, picked_capacity_kw, generators, *, allowed_configurations):
    """Score capacities that were picked (None = nothing feasible) against the actual net load."""
    actual, picks = list(actual_net_kw), list(picked_capacity_kw)
    if not actual or len(actual) != len(picks):
        raise ValueError("Actual net load and picks must be nonempty and equally long")
    equipment, configurations = list(generators), [list(c) for c in allowed_configurations]
    counts = {"undersized_hours": 0, "oversized_hours": 0, "right_sized_hours": 0,
              "infeasible_actual_hours": 0, "infeasible_forecast_hours": 0}
    shortfall_kwh, excess_capacity_kwh = 0.0, 0.0
    for truth, picked in zip(actual, picks):
        truth = max(truth, 0.0)
        needed = recommend(truth, equipment, allowed_configurations=configurations,
                           reserve_margin_fraction=0.0)["selected_capacity_kw"]
        if picked is None:
            counts["infeasible_forecast_hours"] += 1
            continue
        if needed is None:
            counts["infeasible_actual_hours"] += 1
            counts["undersized_hours"] += 1
            shortfall_kwh += truth - picked
            continue
        if picked < truth:
            counts["undersized_hours"] += 1
            shortfall_kwh += truth - picked
        elif picked > needed:
            counts["oversized_hours"] += 1
            excess_capacity_kwh += picked - needed
        else:
            counts["right_sized_hours"] += 1
    hours = len(actual)
    return {"hours": hours, **counts,
            "undersized_share": counts["undersized_hours"] / hours,
            "oversized_share": counts["oversized_hours"] / hours,
            "right_sized_share": counts["right_sized_hours"] / hours,
            "shortfall_kwh": shortfall_kwh, "excess_capacity_kwh": excess_capacity_kwh}


def hold_short_dips(capacities, minimum_hours):
    """Avoid switching down to a smaller configuration for only an hour or two.

    A run of hours shorter than `minimum_hours` that sits between two larger
    capacities is raised to the smaller of its neighbours. Capacity is only
    ever raised, so this cannot create an overload. None (no recommendation)
    is left alone and is never bridged.
    """
    values = list(capacities)
    if minimum_hours <= 1:
        return values
    changed = True
    while changed:
        changed = False
        start = 0
        while start < len(values):
            end = start
            while end + 1 < len(values) and values[end + 1] == values[start]:
                end += 1
            before = values[start - 1] if start > 0 else None
            after = values[end + 1] if end + 1 < len(values) else None
            current = values[start]
            if (current is not None and before is not None and after is not None
                    and end - start + 1 < minimum_hours and before > current and after > current):
                values[start:end + 1] = [min(before, after)] * (end - start + 1)
                changed = True
            start = end + 1
    return values

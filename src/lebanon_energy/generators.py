"""Capacity planning with explicit equipment and operating policy inputs.

This module does not infer ratings from observed peaks or choose a reserve
margin. An hourly recommendation does not certify instantaneous overload
protection, fuel optimality, switching feasibility, or electrical protection.
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

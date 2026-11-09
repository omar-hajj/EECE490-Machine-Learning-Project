"""Strict paired scoring. No acceptance threshold is chosen automatically."""

from dataclasses import asdict, dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class Scores:
    observations: int
    mae: float
    rmse: float
    maximum_absolute_error: float
    mean_actual: float
    nmae: float | None


def score(actual: Iterable[float], predicted: Iterable[float]) -> Scores:
    """nMAE = MAE / mean actual; undefined when every actual is zero.

    Inputs must use the same unit. Missing, negative actuals and non-finite
    values raise an error; they are never silently removed or replaced by zero.
    """
    truth, forecast = list(actual), list(predicted)
    if not truth or len(truth) != len(forecast):
        raise ValueError("Actual and predicted values must be nonempty and equally long")
    if any(not math.isfinite(value) for value in truth + forecast):
        raise ValueError("Forecast scoring requires finite values")
    if any(value < 0 for value in truth):
        raise ValueError("Demand/PV actual values must be nonnegative")
    errors = [prediction - observed for observed, prediction in zip(truth, forecast)]
    mae = math.fsum(abs(error) for error in errors) / len(truth)
    mean_actual = math.fsum(truth) / len(truth)
    return Scores(
        observations=len(truth), mae=mae,
        rmse=math.sqrt(math.fsum(error * error for error in errors) / len(truth)),
        maximum_absolute_error=max(abs(error) for error in errors),
        mean_actual=mean_actual,
        nmae=mae / mean_actual if mean_actual > 0 else None,
    )


def compare_modes(
    actual: Iterable[float], history_predictions: Iterable[float],
    location_predictions: Iterable[float], *,
    maximum_nmae: float | None = None,
    maximum_nmae_gap: float | None = None,
) -> dict:
    """Compare identical observations; a positive gap means location is worse.

    Thresholds are fractions (0.10 means 10%). This scorer does not establish
    that a model was trained without the held-out site; experiment provenance
    and coverage must be checked separately before a deployment decision.
    """
    truth = list(actual)
    history = score(truth, history_predictions)
    location = score(truth, location_predictions)
    thresholds = (maximum_nmae, maximum_nmae_gap)
    if any(value is not None and (not math.isfinite(value) or value < 0) for value in thresholds):
        raise ValueError("Acceptance thresholds must be finite nonnegative fractions")
    gap = None if history.nmae is None else location.nmae - history.nmae
    if history.nmae is None:
        status = "undefined_normalization"
    elif any(value is None for value in thresholds):
        status = "awaiting_acceptance_thresholds"
    elif location.nmae <= maximum_nmae and gap <= maximum_nmae_gap:
        status = "meets_numeric_limits_only"
    else:
        status = "does_not_meet_numeric_limits"
    return {
        "history_based": asdict(history), "location_only": asdict(location),
        "nmae_gap": gap, "status": status,
        "deployment_approved": False,
    }

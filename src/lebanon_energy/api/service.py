"""Azm day-ahead forecast and generator recommendation service.

Clients send a midnight issue time and whatever complete hourly readings
they have (kW, Lebanese local time). The service answers with 24 hourly
forecasts, an upper estimate of net load, the generator configuration that
covers it, and a plain statement of which inputs were missing.

Weather is not an input: forecast weather did not reduce the error in the
rolling-origin check (WEEK2_RESULTS.md), so a missing weather feed cannot
degrade this service. Missing meter history can, and each hour says which
fallback it used. The operator keeps the final decision.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..features.holidays import holiday_aware_features
from ..generators.policy import Generator, hold_short_dips, recommend
from ..models.baselines import predict
from ..models.explain import contributions, describe
from ..models.walk_forward import recent_error_margin

DEFAULT_MODEL_PATH = 'outputs/serving/azm_bundle.joblib'
FALLBACK_REASONS = {'last_week': 'recent_meter_history_missing',
                    'weekday_average': 'recent_and_last_week_meter_history_missing',
                    'unavailable': 'history_and_profile_missing'}


class Reading(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    timestamp_local: datetime
    load_kw: float | None = Field(default=None, ge=0)
    pv_kw: float | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def check_hour(self):
        stamp = self.timestamp_local
        if stamp.tzinfo is not None or any((stamp.minute, stamp.second, stamp.microsecond)):
            raise ValueError('Use a whole hour in Lebanese local time without a UTC offset')
        if self.load_kw is None and self.pv_kw is None:
            raise ValueError('Provide load_kw or pv_kw')
        return self


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    issue_time_local: datetime
    readings: list[Reading] = Field(default_factory=list, max_length=20000)
    apply_fallbacks: bool = Field(default=True, description='False leaves hours without the main model empty '
                                  '(used only to measure what the fallbacks are worth)')

    @model_validator(mode='after')
    def check_history(self):
        issue = self.issue_time_local
        if issue.tzinfo is not None or any((issue.hour, issue.minute, issue.second, issue.microsecond)):
            raise ValueError('Issue time must be midnight in Lebanese local time without a UTC offset')
        zone = ZoneInfo('Asia/Beirut')
        seen = set()
        for reading in self.readings:
            stamp = reading.timestamp_local
            if stamp in seen:
                raise ValueError('Duplicate reading timestamp')
            seen.add(stamp)
            if stamp + timedelta(hours=1) > issue:
                raise ValueError('All hourly readings must be completed by issue time')
            first, second = stamp.replace(tzinfo=zone, fold=0), stamp.replace(tzinfo=zone, fold=1)
            if first.utcoffset() != second.utcoffset():
                raise ValueError('Ambiguous or nonexistent DST reading hour requires clarification')
        # Ordinary 24-hour days only; the two clock-change days per year are refused.
        for hour in range(25):
            stamp = issue + timedelta(hours=hour)
            if stamp.replace(tzinfo=zone, fold=0).utcoffset() != stamp.replace(tzinfo=zone, fold=1).utcoffset():
                raise ValueError('DST transition forecast days are pending explicit clock handling')
        elapsed = ((issue + timedelta(days=1)).replace(tzinfo=zone).astimezone(timezone.utc)
                   - issue.replace(tzinfo=zone).astimezone(timezone.utc))
        if elapsed != timedelta(hours=24):
            raise ValueError('DST transition forecast days are not supported')
        return self


def _chain(series, model, profile, stamp, holidays, apply_fallbacks=True):
    """Main model, then last week's reading, then the stored weekday profile."""
    features, available = holiday_aware_features(series, stamp, holidays)
    if features is not None:
        return float(model.predict([features])[0]), 'ridge', available
    if apply_fallbacks:
        for method in ('last_week', 'weekday_average'):
            result = predict(series, profile, stamp, method)
            if result is not None:
                return result[0], method, result[1]
    return None, 'unavailable', None


def _recent_errors(bundle, net, issue, holidays):
    """Errors of the served model on the days before the issue time.

    Days before the training cutoff use the stored out-of-sample errors;
    later days are computed from the readings in the request. Every error
    belongs to an hour that finished before midnight.
    """
    errors = dict(bundle['stored_ridge_errors_kw'])
    rows, stamps = [], []
    for back in range(1, bundle['recent_error_window_days'] + 1):
        for hour in range(24):
            stamp = issue - timedelta(days=back) + timedelta(hours=hour)
            if stamp < bundle['training_end_exclusive'] or stamp not in net:
                continue
            features, _ = holiday_aware_features(net, stamp, holidays)
            if features is not None:
                rows.append(features)
                stamps.append(stamp)
    if rows:
        for stamp, value in zip(stamps, bundle['models']['net'].predict(rows)):
            errors[stamp] = net[stamp] - float(value)
    return errors


def _peak_drivers(bundle, net, hourly, holidays):
    """Why the highest hour of the plan is what it is (exact Ridge contributions)."""
    planned = [row for row in hourly if row['net_upper_kw'] is not None]
    if not planned:
        return {'available': False, 'reason': 'No forecast was produced.'}
    peak = max(planned, key=lambda row: row['net_upper_kw'])
    if peak['net_method'] != 'ridge' or not hasattr(bundle['models']['net'], 'named_steps'):
        return {'available': False, 'timestamp_local': peak['timestamp_local'],
                'reason': 'The peak hour uses a fallback, which has no input-by-input explanation.'}
    stamp = datetime.fromisoformat(peak['timestamp_local'])
    features, _ = holiday_aware_features(net, stamp, holidays)
    level, parts = contributions(bundle['models']['net'], features)
    return {'available': True, 'timestamp_local': peak['timestamp_local'], 'forecast_kw': peak['net_kw'],
            'upper_kw': peak['net_upper_kw'], 'margin_kw': peak['margin_kw'], 'average_level_kw': level,
            'is_public_holiday': stamp.date() in holidays,
            'drivers': describe(features, parts, stamp, limit=3, holiday=stamp.date() in holidays)}


def _input_status(methods, margin_basis, holiday_known):
    counts = Counter(methods)
    notes = []
    if counts['unavailable']:
        level = 'unavailable'
        notes.append(f"No forecast for {counts['unavailable']} of 24 hours: no usable history or profile.")
    elif counts['ridge'] == 24:
        level = 'full'
        notes.append('Full inputs: every hour uses the main model.')
    else:
        level = 'fallback'
        notes.append(f"Meter history incomplete: {24 - counts['ridge']} of 24 hours use a simpler fallback "
                     f"({counts['last_week']} last week's reading, {counts['weekday_average']} weekday average).")
    if not holiday_known:
        notes.append('Public-holiday calendar does not cover this date; it is treated as a normal day.')
        level = 'fallback' if level == 'full' else level
    if level != 'unavailable' and margin_basis.count('stored_errors'):
        notes.append('Safety margin uses stored errors for some hours because recent history is too short.')
    return {'level': level, 'message': ' '.join(notes), 'net_hours_by_method': dict(counts),
            'weather_required': False, 'holiday_calendar_known': holiday_known}


def forecast(bundle, request):
    issue = request.issue_time_local
    if issue < bundle['training_end_exclusive']:
        raise ValueError('Issue time precedes the model training cutoff')
    holidays = set(bundle['holidays'])
    holiday_known = any(start <= issue.date() <= end for start, end in bundle['holiday_covered_periods'])
    load = {r.timestamp_local: r.load_kw for r in request.readings if r.load_kw is not None}
    pv = {r.timestamp_local: r.pv_kw for r in request.readings if r.pv_kw is not None}
    net = {stamp: load[stamp] - pv[stamp] for stamp in load.keys() & pv.keys()}
    policy = bundle['generator_policy']
    generators = [Generator(item['generator_id'], float(item['usable_capacity_kw']), item.get('available', True))
                  for item in policy['generators']]
    reserve = float(policy['reserve_margin_fraction'])
    errors = _recent_errors(bundle, net, issue, holidays)
    hourly, methods, basis = [], [], []
    for hour in range(24):
        stamp = issue + timedelta(hours=hour)
        demand, load_method, _ = _chain(load, bundle['models']['load'], bundle['profiles']['load'], stamp,
                                        holidays, request.apply_fallbacks)
        solar_result = predict(pv, bundle['profiles']['pv'], stamp, 'weekday_average')
        solar = solar_result[0] if solar_result else None
        net_value, method, available = _chain(net, bundle['models']['net'], bundle['profiles']['net'], stamp,
                                              holidays, request.apply_fallbacks)
        margin, margin_basis = None, None
        if method == 'ridge':
            margin = recent_error_margin(errors, issue, hour, quantile=bundle['quantile'],
                                         window_days=bundle['recent_error_window_days'],
                                         minimum_days=bundle['recent_error_minimum_days'])
            margin_basis = 'recent_errors'
        if margin is None and method != 'unavailable':
            margin, margin_basis = bundle['stored_margins_kw'].get(method, {}).get(hour), 'stored_errors'
        upper = net_value + margin if net_value is not None and margin is not None else None
        if any(value is not None and not math.isfinite(value) for value in (demand, solar, net_value, upper)):
            raise ValueError('Model produced a nonfinite value')
        if upper is None:
            advice = {'status': 'unavailable', 'configurations': [], 'capacity_kw': None, 'required_capacity_kw': None}
        else:
            choice = recommend(max(upper, 0.0), generators, allowed_configurations=policy['allowed_configurations'],
                               reserve_margin_fraction=reserve)
            advice = {'status': choice['status'], 'configurations': choice['candidate_configurations'],
                      'capacity_kw': choice['selected_capacity_kw'], 'required_capacity_kw': choice['required_capacity_kw']}
        methods.append(method)
        basis.append(margin_basis)
        hourly.append({'timestamp_local': stamp.isoformat(), 'load_kw': demand, 'pv_kw': solar,
                       'net_kw': net_value, 'net_upper_kw': upper, 'load_method': load_method,
                       'net_method': method, 'net_fallback_reason': FALLBACK_REASONS.get(method),
                       'margin_kw': margin, 'margin_basis': margin_basis,
                       'net_latest_input_available_at_local': available.isoformat() if available else None,
                       'negative_load_prediction': demand is not None and demand < 0,
                       'generator': advice})
    # Hold the larger configuration through dips shorter than the minimum run (capacity only goes up).
    minimum_run = int(policy.get('minimum_run_hours', 1))
    by_capacity = {}
    for configuration in policy['allowed_configurations']:
        capacity = math.fsum(g.usable_capacity_kw for g in generators if g.generator_id in configuration)
        by_capacity.setdefault(capacity, []).append(sorted(configuration))
    held = hold_short_dips([row['generator']['capacity_kw'] for row in hourly], minimum_run)
    for row, capacity in zip(hourly, held):
        row['generator']['held_through_short_dip'] = capacity != row['generator']['capacity_kw']
        if row['generator']['held_through_short_dip']:
            row['generator'].update(capacity_kw=capacity, configurations=by_capacity[capacity])
    return {'site_id': 'azm', 'timezone': 'Asia/Beirut', 'units': 'kW', 'issue_time_local': issue.isoformat(),
            'peak_drivers': _peak_drivers(bundle, net, hourly, holidays),
            'status': 'development_not_final_tested',
            'model_training_end_exclusive': bundle['training_end_exclusive'].isoformat(),
            'source_sha256': bundle['source_sha256'],
            'input_status': _input_status(methods, basis, holiday_known),
            'upper_estimate': {'target_quantile': bundle['quantile'],
                               'basis': 'point forecast plus the upper range of its errors on recent days',
                               'window_days': bundle['recent_error_window_days']},
            'generator_policy': {'status': policy['status'], 'reserve_margin_fraction': reserve,
                                 'rule': policy['selection_rule'],
                                 'minimum_run_hours': minimum_run,
                                 'capacities_kw': {g.generator_id: g.usable_capacity_kw for g in generators},
                                 'allowed_configurations': policy['allowed_configurations']},
            'limitations': ['Azm only. Advice is hourly-average sizing: it does not cover instantaneous peaks, '
                            'switching limits or fuel optimality.',
                            'Capacities are the highest outputs observed in the data, not confirmed ratings.',
                            'The upper estimate is empirical (about 9 hours in 10), not a guarantee.',
                            'The operator keeps the final decision.'],
            'hourly': hourly}


def create_app(bundle=None):
    app = FastAPI(title='Azm day-ahead forecast and generator advice', version='0.2.0')

    def model_path():
        return Path(os.environ.get('AZM_MODEL_PATH', DEFAULT_MODEL_PATH))

    @app.get('/health')
    def health():
        return {'status': 'ready' if bundle is not None or model_path().is_file() else 'model_missing'}

    @app.post('/forecast')
    def endpoint(request: ForecastRequest):
        nonlocal bundle
        if bundle is None:
            import joblib
            if not model_path().is_file():
                raise HTTPException(503, 'Run scripts/build_serving_bundle.py to build the model bundle')
            bundle = joblib.load(model_path())
        try:
            return forecast(bundle, request)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    return app


app = create_app()

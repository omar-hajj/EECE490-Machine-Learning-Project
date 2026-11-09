"""Local Azm forecast demo. Clients supply complete hourly averages in kW."""
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .baselines import predict
from .features import history_calendar_features


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

    @model_validator(mode='after')
    def check_history(self):
        issue = self.issue_time_local
        if issue.tzinfo is not None or any((issue.hour, issue.minute, issue.second, issue.microsecond)):
            raise ValueError('Issue time must be midnight in Lebanese local time without a UTC offset')
        seen = set()
        for reading in self.readings:
            stamp = reading.timestamp_local
            if stamp in seen:
                raise ValueError('Duplicate reading timestamp')
            seen.add(stamp)
            if stamp + timedelta(hours=1) > issue:
                raise ValueError('All hourly readings must be completed by issue time')
            zone = ZoneInfo('Asia/Beirut')
            first, second = stamp.replace(tzinfo=zone, fold=0), stamp.replace(tzinfo=zone, fold=1)
            if first.utcoffset() != second.utcoffset():
                raise ValueError('Ambiguous or nonexistent DST reading hour requires clarification')
        zone = ZoneInfo('Asia/Beirut')
        # This first demo serves ordinary 24-hour days only.
        for hour in range(25):
            stamp = issue + timedelta(hours=hour)
            if stamp.replace(tzinfo=zone, fold=0).utcoffset() != stamp.replace(tzinfo=zone, fold=1).utcoffset():
                raise ValueError('DST transition forecast days are pending explicit clock handling')
        elapsed = ((issue + timedelta(days=1)).replace(tzinfo=zone).astimezone(timezone.utc)
                   - issue.replace(tzinfo=zone).astimezone(timezone.utc))
        if elapsed != timedelta(hours=24):
            raise ValueError('DST transition forecast days are not supported in this demo')
        return self


def forecast(bundle, request):
    issue = request.issue_time_local
    if issue < bundle['training_end_exclusive']:
        raise ValueError('Issue time precedes the model training cutoff')
    load = {r.timestamp_local: r.load_kw for r in request.readings if r.load_kw is not None}
    pv = {r.timestamp_local: r.pv_kw for r in request.readings if r.pv_kw is not None}
    hourly = []
    for hour in range(24):
        stamp = issue + timedelta(hours=hour)
        features, available = history_calendar_features(load, stamp)
        if features is not None:
            demand = float(bundle['model'].predict([features])[0])
            method, reason = 'ridge', None
        else:
            result = predict(load, bundle['profiles']['load'], stamp, 'last_week')
            method, reason = 'last_week', 'required_ridge_lag_missing'
            if result is None:
                result = predict(load, bundle['profiles']['load'], stamp, 'weekday_average')
                method, reason = 'weekday_average', 'required_ridge_lag_and_last_week_missing'
            demand, available = result if result is not None else (None, None)
            if result is None:
                method, reason = 'unavailable', 'history_and_profile_missing'
        solar_result = predict(pv, bundle['profiles']['pv'], stamp, 'weekday_average')
        solar, solar_available = solar_result if solar_result is not None else (None, None)
        if any(value is not None and not math.isfinite(value) for value in (demand, solar)):
            raise ValueError('Model produced a nonfinite value')
        hourly.append({'timestamp_local': stamp.isoformat(), 'load_kw': demand, 'pv_kw': solar,
            'signed_net_kw': demand - solar if demand is not None and solar is not None else None,
            'load_method': method, 'load_fallback_reason': reason,
            'pv_method': 'weekday_average' if solar_result else 'unavailable',
            'load_latest_input_available_at_local': available.isoformat() if available else None,
            'pv_latest_input_available_at_local': solar_available.isoformat() if solar_available else None,
            'negative_load_prediction': demand is not None and demand < 0})
    return {'site_id': 'azm', 'timezone': 'Asia/Beirut', 'units': 'kW',
        'issue_time_local': issue.isoformat(), 'status': 'development_demo_not_final_tested',
        'model_training_end_exclusive': bundle['training_end_exclusive'].isoformat(),
        'model_selection_period': bundle['selection_period'], 'source_sha256': bundle['source_sha256'],
        'generator_advice': {'available': False, 'reason': 'Equipment capacities, allowed combinations and reserve policy are missing'},
        'limitations': ['Azm model only; nationwide performance is not established.',
            'Raw model predictions are returned without clipping.',
            'Readings must be complete hourly averages; receipt delays are not established.',
            'P90 calibration is experimental and is not served as a guarantee.'],
        'hourly': hourly}


def create_app(bundle=None):
    app = FastAPI(title='Lebanon Energy — Azm demo', version='0.1.0')

    @app.get('/health')
    def health():
        path = Path(os.environ.get('AZM_MODEL_PATH', 'outputs/azm_backtest/azm_demo.joblib'))
        return {'status': 'ready' if bundle is not None or path.is_file() else 'model_missing'}

    @app.post('/forecast')
    def endpoint(request: ForecastRequest):
        nonlocal bundle
        if bundle is None:
            import joblib
            path = Path(os.environ.get('AZM_MODEL_PATH', 'outputs/azm_backtest/azm_demo.joblib'))
            if not path.is_file():
                raise HTTPException(503, 'Run the Azm backtest script to build the local demo model')
            bundle = joblib.load(path)
        try:
            return forecast(bundle, request)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    return app


app = create_app()

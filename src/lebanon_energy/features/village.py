"""Confirmed-unit loading and strict location-only feature construction."""

from collections import defaultdict
from datetime import datetime
import csv
import json
import math

from ..features.history import history_calendar_features
from ..data.weather import VARIABLES, aligned_features


def load_series_kw(path, sites, site_ids, cutoff):
    metadata = {site['site_id']: site for site in sites['sites']}
    result = defaultdict(dict)
    for site_id in site_ids:
        site = metadata[site_id]
        if site.get('clock_verification_status', '').startswith('conflict'):
            raise ValueError('Unresolved source clock conflict prevents weather alignment')
        if site.get('power_unit_confirmed') not in {'W', 'kW'}:
            raise ValueError('Source unit must be confirmed')
        if site.get('meter_clock') != 'Asia/Beirut' or not site.get('meter_clock_observes_dst'):
            raise ValueError('Meter clock must be confirmed')
    with path.open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['site_id'] not in site_ids:
                continue
            timestamp = datetime.fromisoformat(row['timestamp_local_unverified'])
            if timestamp >= cutoff:
                raise ValueError('Reserved test target appeared in prepared input')
            factor = .001 if metadata[row['site_id']]['power_unit_confirmed'] == 'W' else 1.
            value = float(row['value_source_units']) * factor
            if not math.isfinite(value) or value < 0:
                raise ValueError('Prepared target must be finite and nonnegative')
            key = row['site_id'], row['target']
            if timestamp in result[key]:
                raise ValueError('Duplicate prepared target')
            result[key][timestamp] = value
    return result


def load_village_weather(path):
    values = {}
    with path.open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            stamp = datetime.fromisoformat(row['valid_time_utc'])
            if stamp.tzinfo is None:
                raise ValueError('Weather must have an explicit UTC offset')
            if stamp in values:
                raise ValueError('Duplicate weather valid time')
            values[stamp] = {feature: float(row[prefix]) for feature, (prefix, _) in VARIABLES.items()}
    return values


def location_features(timestamp, weather_entry, latitude, longitude):
    """Signature deliberately accepts no site ID, meter readings or scale."""
    if weather_entry is None:
        return None, None
    issue = timestamp.replace(hour=0)
    if weather_entry['nominal_available_at_local'] > issue:
        raise ValueError('Nominal forecast weather is unavailable at issue time')
    angle = 2 * math.pi * (timestamp.timetuple().tm_yday - 1) / 365.25
    features = {'latitude': latitude, 'longitude': longitude,
                'hour_of_week': str(timestamp.weekday() * 24 + timestamp.hour),
                'day_of_year_sin': math.sin(angle), 'day_of_year_cos': math.cos(angle)}
    if set(weather_entry['features']) != set(VARIABLES):
        raise ValueError('Only the six forecast weather variables are allowed')
    features.update(weather_entry['features'])
    return features, weather_entry['nominal_available_at_local']


def history_features(series, timestamp, weather_entry, latitude, longitude):
    features, available = location_features(timestamp, weather_entry, latitude, longitude)
    lags, lag_available = history_calendar_features(series, timestamp)
    if features is None or lags is None:
        return None, None
    features.update({name: value for name, value in lags.items() if name.startswith('lag_')})
    return features, max(available, lag_available)


def check_holdout(training_sites, heldout_sites):
    if not training_sites or set(training_sites) & set(heldout_sites):
        raise ValueError('Held-out site cannot enter location-only training or tuning')
    pair = {'household_1', 'household_2'}
    if pair & set(heldout_sites) and not pair <= set(heldout_sites):
        raise ValueError('Known duplicated-source households must be held out together')

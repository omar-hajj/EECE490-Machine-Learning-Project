"""Align nominal day-ahead weather with confirmed Lebanese meter hours.

Publication timing is not present in the supplied CSV. Availability returned
here is nominal only, using the documented previous_day1 lead. It must not
be described as verified historical publication availability.
"""

import csv
from datetime import datetime, timedelta, timezone
import io
import math
from zoneinfo import ZoneInfo


VARIABLES = {
    "forecast_temperature": ("temperature_2m_previous_day1", False),
    "forecast_humidity": ("relative_humidity_2m_previous_day1", False),
    "forecast_cloud_cover": ("cloud_cover_previous_day1", False),
    "forecast_shortwave_radiation": ("shortwave_radiation_previous_day1", True),
    "forecast_diffuse_radiation": ("diffuse_radiation_previous_day1", True),
    "forecast_direct_radiation": ("direct_radiation_previous_day1", True),
}


def read_forecast_csv(content, cutoff):
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    metadata = dict(zip(rows[0], rows[1]))
    header_index = next(index for index, row in enumerate(rows) if row and row[0] == "time")
    columns = rows[header_index]
    indices = {}
    for feature, (prefix, _) in VARIABLES.items():
        matches = [index for index, column in enumerate(columns) if column.startswith(prefix + " (")]
        if len(matches) != 1:
            raise ValueError("Expected exactly one forecast column for " + prefix)
        indices[feature] = matches[0]
    fixed_timezone = timezone(timedelta(seconds=int(metadata["utc_offset_seconds"])))
    values = {}
    for row in rows[header_index + 1:]:
        if not row:
            continue
        recorded = datetime.fromisoformat(row[0])
        if recorded.tzinfo is not None:
            raise ValueError("Expected naive CSV timestamps with a fixed offset in metadata")
        if recorded >= cutoff:
            continue
        valid_utc = recorded.replace(tzinfo=fixed_timezone).astimezone(timezone.utc)
        if valid_utc in values:
            raise ValueError("Repeated weather valid time")
        features = {feature: float(row[index]) for feature, index in indices.items()}
        if not all(math.isfinite(value) for value in features.values()):
            raise ValueError("Non-finite forecast input")
        values[valid_utc] = features
    return metadata, values


def aligned_features(weather_values, target_hour, meter_timezone="Asia/Beirut"):
    if target_hour.tzinfo is not None or any((target_hour.minute, target_hour.second, target_hour.microsecond)):
        raise ValueError("Expected a naive hourly meter timestamp")
    zone = ZoneInfo(meter_timezone)
    local = target_hour.replace(tzinfo=zone)
    if local.utcoffset() != target_hour.replace(tzinfo=zone, fold=1).utcoffset():
        raise ValueError("Ambiguous/nonexistent meter hour requires a source-clock decision")
    start_utc = local.astimezone(timezone.utc)
    issue_local = target_hour.replace(hour=0)
    issue_utc = issue_local.replace(tzinfo=zone).astimezone(timezone.utc)
    result, nominal_times = {}, []
    for feature, (_, preceding_hour_mean) in VARIABLES.items():
        # A radiation value at 13:00 describes 12:00-13:00. Temperature at
        # 12:00 is a sample at that instant. Align those timestamps separately.
        valid_utc = start_utc + timedelta(hours=1 if preceding_hour_mean else 0)
        source = weather_values.get(valid_utc)
        if source is None:
            return None
        result[feature] = source[feature]
        nominal_time = valid_utc - timedelta(hours=24)
        if nominal_time > issue_utc:
            raise ValueError("Nominal forecast input is later than the forecast issue time")
        nominal_times.append(nominal_time)
    latest = max(nominal_times)
    return {"features": result,
            "nominal_available_at_local": latest.astimezone(zone).replace(tzinfo=None),
            "nominal_available_at_utc": latest,
            "nominal_margin_hours": (issue_utc - latest).total_seconds() / 3600,
            "publication_availability_verified": False}

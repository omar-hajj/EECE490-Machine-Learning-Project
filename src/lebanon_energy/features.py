"""Forecast inputs limited to information available at midnight."""

from datetime import timedelta


def history_calendar_features(series, timestamp, lag_hours=(24, 168)):
    """Return (feature dictionary, latest input availability) or (None, None).

    Series values are completed hourly measurements on the unshifted source
    clock. Every lag uses an exact timestamp lookup, never a row offset.
    A completed hour is assumed available at its end, as in the approved
    baseline protocol. No meter transmission delay has been established.
    """
    if timestamp.tzinfo is not None or any((timestamp.minute, timestamp.second, timestamp.microsecond)):
        raise ValueError("Expected an exact hour on the naive recorded source clock")
    if not lag_hours or len(set(lag_hours)) != len(lag_hours):
        raise ValueError("Distinct historical lag hours are required")
    issue_time = timestamp.replace(hour=0)
    features = {"hour_of_week": str(timestamp.weekday() * 24 + timestamp.hour)}
    available_at = []
    for lag in lag_hours:
        if not isinstance(lag, int) or lag <= 0:
            raise ValueError("Lag hours must be positive integers")
        source_hour = timestamp - timedelta(hours=lag)
        knowledge_time = source_hour + timedelta(hours=1)
        if knowledge_time > issue_time:
            raise ValueError("Lag value is unavailable at the midnight forecast issue time")
        value = series.get(source_hour)
        if value is None:
            return None, None
        features[f"lag_{lag}h"] = value
        available_at.append(knowledge_time)
    return features, max(available_at)

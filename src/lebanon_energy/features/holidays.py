"""History features that know about public holidays.

Public holidays are announced in advance, so they are known at the midnight
issue time. Two things go wrong when they are ignored:

- the holiday itself is forecast like a normal working day (over-forecast);
- one week later, "same hour last week" points at the holiday and the
  forecast is far too low, which is the overload-risk direction.

A holiday is therefore treated as a Sunday, and a weekly lag that would land
on a holiday steps back one more week. Every lookup still uses an exact
timestamp and data completed before the issue time.
"""

from datetime import timedelta

from .history import history_calendar_features

SUNDAY = 6
MAXIMUM_EXTRA_WEEKS = 2


def _most_recent_sunday_hour(timestamp, holidays):
    """Same clock hour on the latest Sunday strictly before the issue day."""
    day = timestamp.replace(hour=0) - timedelta(days=1)
    while day.weekday() != SUNDAY:
        day -= timedelta(days=1)
    return day.replace(hour=timestamp.hour)


def holiday_aware_features(series, timestamp, holidays):
    """Return (features, latest input availability) or (None, None).

    Same inputs as history_calendar_features (hour of week, 24 h and 168 h
    lags), with holiday handling. `holidays` is a set of dates.
    """
    issue_time = timestamp.replace(hour=0)
    if timestamp.date() in holidays:
        recent = _most_recent_sunday_hour(timestamp, holidays)
        sources = {"lag_24h": recent, "lag_168h": recent - timedelta(days=7)}
        hour_of_week = SUNDAY * 24 + timestamp.hour
    else:
        base, _ = history_calendar_features(series, timestamp)  # validates the timestamp
        weekly = timestamp - timedelta(hours=168)
        extra = 0
        while weekly.date() in holidays and extra < MAXIMUM_EXTRA_WEEKS:
            weekly -= timedelta(days=7)
            extra += 1
        sources = {"lag_24h": timestamp - timedelta(hours=24), "lag_168h": weekly}
        hour_of_week = timestamp.weekday() * 24 + timestamp.hour
    features, available = {"hour_of_week": str(hour_of_week)}, []
    for name, source in sources.items():
        value = series.get(source)
        if value is None:
            return None, None
        known_at = source + timedelta(hours=1)
        if known_at > issue_time:
            raise ValueError("Lag value is unavailable at the midnight forecast issue time")
        features[name] = value
        available.append(known_at)
    # Yesterday being a holiday makes the 24 h lag unrepresentative; let the model see that.
    features["lag_24h_is_holiday"] = float(sources["lag_24h"].date() in holidays and timestamp.date() not in holidays)
    return features, max(available)

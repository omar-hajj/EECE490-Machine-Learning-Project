"""Reading the source ZIP and the approved complete-hour preparation.

Split from the original baselines.py. Values keep their source units; the
reserved test period is excluded before aggregation. See BASELINE_PROTOCOL.md.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import hashlib
import importlib
import io
import math
from pathlib import Path
import re
import warnings
from zipfile import ZipFile

from .audit import MONTHS, parse_timestamp


def hourly_means(records, *, targets, sampling_minutes, cutoff):
    """Return per-target complete-hour means and explicit exclusion counts.

    records are (timestamp, {target: original value}) pairs. All nominal slots
    must occur exactly once, with usable values. Duplicate timestamps raise
    an error; an hour with multiple records in one slot is excluded. The
    means use the equal-weight arithmetic averaging approved for this run.
    """
    if sampling_minutes <= 0 or 60 % sampling_minutes:
        raise ValueError("Sampling interval must divide an hour")
    expected = 60 // sampling_minutes
    buckets = defaultdict(list)
    seen = set()
    included, excluded_test = 0, 0
    for timestamp, values in records:
        if timestamp.tzinfo is not None:
            raise ValueError("This protocol requires unshifted, naive source-clock timestamps")
        if timestamp >= cutoff:
            excluded_test += 1
            continue
        if timestamp in seen:
            raise ValueError(f"Repeated source timestamp: {timestamp}")
        seen.add(timestamp)
        hour = timestamp.replace(minute=0, second=0, microsecond=0)
        slot = timestamp.minute // sampling_minutes
        buckets[hour].append((slot, values))
        included += 1
    hourly = {target: {} for target in targets}
    exclusions = {target: Counter() for target in targets}
    for hour, samples in sorted(buckets.items()):
        slots = [slot for slot, _ in samples]
        complete = len(samples) == expected and set(slots) == set(range(expected))
        for target in targets:
            if not complete:
                exclusions[target]["incomplete_or_repeated_sampling_slots"] += 1
                continue
            values = []
            for _, sample in samples:
                try:
                    value = float(sample.get(target))
                except (TypeError, ValueError):
                    break
                if not math.isfinite(value) or value < 0:
                    break
                values.append(value)
            if len(values) != expected:
                exclusions[target]["missing_nonnumeric_nonfinite_or_negative_value"] += 1
                continue
            hourly[target][hour] = math.fsum(values) / expected
    return hourly, {
        "included_raw_records": included,
        "reserved_or_later_raw_records_excluded": excluded_test,
        "observed_hour_buckets": len(buckets),
        "expected_readings_per_hour": expected,
        "exclusions_by_target": {target: dict(counts) for target, counts in exclusions.items()},
        "retained_hours_by_target": {target: len(series) for target, series in hourly.items()},
    }


def mask_frozen_readings(records, *, targets, sampling_minutes, minimum_consecutive_readings):
    """Blank readings where every target channel is stuck on the same values.

    A frozen stretch is at least minimum_consecutive_readings consecutive
    readings, exactly sampling_minutes apart, whose target values are all
    identical to the first reading of the stretch and are not all zero
    (zeros are normal: no solar at night, no load during an outage).
    Masked readings keep their timestamp but lose their values, so the
    complete-hour rule drops the affected hours. Returns (records, stretches).
    """
    if minimum_consecutive_readings < 2:
        raise ValueError("A frozen stretch needs at least two readings")
    rows = sorted(records, key=lambda row: row[0])
    step = timedelta(minutes=sampling_minutes)
    stretches, masked = [], set()
    start = 0
    for index in range(1, len(rows) + 1):
        continues = (index < len(rows)
                     and rows[index][0] - rows[index - 1][0] == step
                     and all(rows[index][1].get(t) == rows[start][1].get(t) for t in targets))
        if continues:
            continue
        length = index - start
        values = {t: rows[start][1].get(t) for t in targets}
        numeric = []
        for value in values.values():
            try:
                numeric.append(float(value))
            except (TypeError, ValueError):
                numeric = None
                break
        if length >= minimum_consecutive_readings and numeric and any(v != 0 for v in numeric):
            masked.update(range(start, index))
            stretches.append({"start": rows[start][0].isoformat(), "end": rows[index - 1][0].isoformat(),
                              "readings": length, "values": values})
        start = index
    cleaned = [(stamp, {t: None for t in values}) if i in masked else (stamp, values)
               for i, (stamp, values) in enumerate(rows)]
    return cleaned, stretches


def _read_records(content, label, profile, counters):
    from openpyxl import load_workbook

    filename_month = next((number for name, number in MONTHS.items() if name in Path(label).name), None)
    cutoff = datetime.fromisoformat(profile["validation_end_exclusive"])
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        if len(book.worksheets) != 1:
            raise ValueError(f"Expected one measurement worksheet: {label}")
        rows = book.worksheets[0].iter_rows(values_only=True)
        headers = list(next(rows))
        time_index = headers.index("Time")
        indices = {target: headers.index(column) for target, column in profile["targets"].items()}
        previous = None
        for row in rows:
            if not any(value is not None for value in row):
                continue
            timestamp, interpretation = parse_timestamp(row[time_index], filename_month)
            if timestamp is None:
                raise ValueError(f"Unresolved source timestamp in {label}: {row[time_index]!r}")
            counters["timestamp_interpretations"][interpretation] += 1
            if timestamp >= cutoff:
                counters["reserved_or_later_rows_not_used"] += 1
                continue
            if previous is not None:
                interval = (timestamp - previous).total_seconds()
                if interval > 0:
                    counters["positive_intervals_seconds"][interval] += 1
            previous = timestamp
            yield timestamp, {target: row[index] for target, index in indices.items()}
    finally:
        book.close()


def _site_records(archive, site, profile, counters):
    label = site["source_label"]
    matches = [member for member in archive.infolist() if Path(member.filename).name == label]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one source archive member for {site['site_id']}")
    source = matches[0]
    if label.lower().endswith(".xlsx"):
        counters["workbooks_read"] += 1
        yield from _read_records(archive.read(source), source.filename, profile, counters)
    elif label.lower().endswith(".zip"):
        with ZipFile(io.BytesIO(archive.read(source))) as nested:
            cutoff = datetime.fromisoformat(profile["validation_end_exclusive"])
            for member in nested.infolist():
                if not member.filename.lower().endswith(".xlsx"):
                    continue
                month = next((number for name, number in MONTHS.items() if name in member.filename), None)
                years = [int(part) for part in re.findall(r"\b20\d{2}\b", member.filename)]
                if month is not None and len(years) == 1 and datetime(years[0], month, 1) >= cutoff:
                    counters["reserved_workbooks_not_opened"].append(member.filename)
                    continue
                counters["workbooks_read"] += 1
                yield from _read_records(nested.read(member), member.filename, profile, counters)
    else:
        raise ValueError(f"Unsupported source type: {label}")


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_path(module_name):
    """File of a lebanon_energy module (for example "features.history"), for code hashes."""
    return Path(importlib.import_module(f"lebanon_energy.{module_name}").__file__)

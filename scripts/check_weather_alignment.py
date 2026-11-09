"""Check supplied weather exports without choosing an unknown meter clock."""

import argparse
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import math
from pathlib import Path
from zipfile import ZipFile


def inspect(content, name, cutoff):
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    metadata = dict(zip(rows[0], rows[1]))
    header_index = next(index for index, row in enumerate(rows) if row and row[0] == "time")
    header = rows[header_index]
    seen, intervals, previous, invalid = set(), Counter(), None, Counter()
    first = last = None
    for row in rows[header_index + 1:]:
        if not row:
            continue
        timestamp = datetime.fromisoformat(row[0])
        if timestamp >= cutoff:
            continue
        if timestamp in seen:
            raise ValueError(f"Repeated weather timestamp in {name}")
        seen.add(timestamp)
        if previous is not None:
            intervals[str((timestamp - previous).total_seconds())] += 1
        previous = timestamp
        first = min(first or timestamp, timestamp)
        last = max(last or timestamp, timestamp)
        for column, value in zip(header[1:], row[1:]):
            try:
                if not math.isfinite(float(value)):
                    invalid[column] += 1
            except (TypeError, ValueError):
                invalid[column] += 1
    fixed_offset = timezone(timedelta(seconds=int(metadata["utc_offset_seconds"])))
    example = datetime(2026, 7, 1, 12)
    return {
        "source": name, "metadata": metadata, "columns": header,
        "records_before_reserved_test": len(seen),
        "first_timestamp": first.isoformat() if first else None,
        "last_timestamp": last.isoformat() if last else None,
        "interval_counts_seconds": dict(intervals), "invalid_values": dict(invalid),
        "example_csv_clock": example.isoformat(),
        "example_utc_from_fixed_metadata": example.replace(tzinfo=fixed_offset).astimezone(timezone.utc).isoformat(),
        "forecast_lead_label": "previous_day1" if any("previous_day1" in column for column in header) else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sites", type=Path, default=Path("config/sites.json"))
    args = parser.parse_args()
    if args.output.suffix.lower() != ".json":
        parser.error("Expected a JSON report output")
    azm = next((site for site in json.loads(args.sites.read_text(encoding="utf-8"))["sites"] if site["site_id"] == "azm"), {})
    report = {
        "meter_clock": azm.get("meter_clock", "awaiting_user_confirmation"),
        "meter_clock_confirmed_by_user": bool(azm.get("meter_clock_confirmation_source")), "weather_join_applied": False,
        "weather_used_for_ridge": False, "reserved_test_weather_analyzed": False,
        "files": [],
        "findings": [
            "Both CSV metadata blocks specify fixed UTC+2, despite the Asia/Beirut timezone label.",
            "Open-Meteo says ISO local output uses the fixed response UTC offset; daylight-saving conversion must not be guessed.",
            "Solar radiation is the mean over the preceding hour. Its valid-time endpoint differs from the start of a prepared meter-hour bucket.",
            "Temperature, humidity and cloud cover use valid-time samples; radiation and instantaneous fields need separate alignment rules.",
            "previous_day1 indicates nominal 24-hour lead. Original request/model-run/publication provenance is not included in the CSV.",
            "Observed future weather must not be supplied as a forecasting input.",
            "Different returned coordinates can describe different model grid cells; they do not prove a wrong site.",
        ],
        "required_before_join": ([] if azm.get("meter_clock_confirmation_source") else ["Confirm meter clock"]) + ["Confirm original weather download/model provenance",
                                 "Map radiation intervals and instantaneous valid times separately",
                                 "Establish feature availability by the midnight forecast issue time"],
        "references": ["https://open-meteo.com/en/docs", "https://open-meteo.com/en/docs/previous-runs-api"],
    }
    with ZipFile(args.archive) as archive:
        for name in archive.namelist():
            if name.endswith(("azm_weather_forecast_day1.csv.csv", "azm_weather_observed.csv.csv")):
                report["files"].append(inspect(archive.read(name), name, datetime(2026, 9, 1)))
    if len(report["files"]) != 2:
        raise ValueError("Expected both supplied Azm weather CSVs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Checked two weather files through August. No meter-clock conversion or weather join applied. Report: {args.output}")


if __name__ == "__main__":
    main()

"""Lebanese public holidays from config/lebanon_public_holidays.csv.

Every date in the file has a source and a confidence level (high = official
list or government closure notice; medium = marked tentative by the source,
or announced but not read in full). See DATA_PROVENANCE.md, check 4.
"""

import argparse
from collections import Counter
import csv
from datetime import date, datetime
import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "lebanon_public_holidays.csv"
CONFIDENCE_LEVELS = {"high", "medium"}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# Periods the holiday file was researched for (inclusive). Outside them the
# holiday columns are left blank (unknown) instead of claiming a working day.
COVERED_PERIODS = ((date(2024, 8, 1), date(2024, 9, 30)),
                   (date(2024, 12, 1), date(2025, 7, 31)),
                   (date(2026, 4, 16), date(2026, 9, 30)))
CALENDAR_COLUMNS = ("hour", "weekday", "is_weekend", "is_public_holiday", "public_holiday_name",
                    "public_holiday_confidence", "is_school_holiday")


def load_public_holidays(path=DEFAULT_PATH):
    """Return {date: row} and refuse a file with gaps, duplicates or unsourced dates."""
    holidays = {}
    with Path(path).open(encoding="utf-8", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), start=2):
            day = date.fromisoformat(row["date"])
            if day in holidays:
                raise ValueError(f"Line {line}: {day} is listed twice")
            if not row["name"].strip() or not row["source_url"].startswith("http"):
                raise ValueError(f"Line {line}: every holiday needs a name and a source link")
            if row["confidence"] not in CONFIDENCE_LEVELS:
                raise ValueError(f"Line {line}: confidence must be one of {sorted(CONFIDENCE_LEVELS)}")
            holidays[day] = row
    if list(holidays) != sorted(holidays):
        raise ValueError("Holiday dates must be in order")
    outside = [day for day in holidays if not _covered(day)]
    if outside:
        raise ValueError(f"Holidays outside the researched periods: {outside}")
    return holidays


def _covered(day):
    return any(start <= day <= end for start, end in COVERED_PERIODS)


def calendar_columns(timestamp, holidays):
    """Calendar facts for one hour, all known before the forecast is made.

    is_weekend is Saturday or Sunday; Azm's data shows both quiet, with Friday
    a shorter working day. Holiday columns are None outside COVERED_PERIODS.
    School holidays are None everywhere until Azm's academic calendar arrives.
    """
    day = timestamp.date()
    covered = _covered(day)
    holiday = holidays.get(day)
    return {"hour": timestamp.hour, "weekday": WEEKDAYS[day.weekday()], "is_weekend": day.weekday() >= 5,
            "is_public_holiday": (holiday is not None) if covered else None,
            "public_holiday_name": holiday["name"] if holiday else None,
            "public_holiday_confidence": holiday["confidence"] if holiday else None,
            "is_school_holiday": None}


def build_calendar_table(hourly_csv, holidays):
    """One calendar row per (site, hour) found in the pipeline's hourly_data.csv."""
    keys = set()
    with Path(hourly_csv).open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            keys.add((row["site_id"], datetime.fromisoformat(row["timestamp_local_unverified"])))
    return [{"site_id": site, "timestamp_local": stamp.isoformat(), **calendar_columns(stamp, holidays)}
            for site, stamp in sorted(keys)]


def main():
    parser = argparse.ArgumentParser(description="Write calendar columns for every hour in the hourly data.")
    parser.add_argument("--hourly-data", type=Path, default=Path("outputs/baselines_confirmed_azm/hourly_data.csv"))
    parser.add_argument("--holidays", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/calendar"))
    args = parser.parse_args()
    rows = build_calendar_table(args.hourly_data, load_public_holidays(args.holidays))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "hourly_calendar.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["site_id", "timestamp_local", *CALENDAR_COLUMNS])
        writer.writeheader()
        writer.writerows(rows)
    summary = {}
    for site in sorted({row["site_id"] for row in rows}):
        mine = [row for row in rows if row["site_id"] == site]
        summary[site] = {"hours": len(mine),
                         "weekend_hours": sum(row["is_weekend"] for row in mine),
                         "public_holiday_hours": sum(row["is_public_holiday"] is True for row in mine),
                         "holiday_unknown_hours": sum(row["is_public_holiday"] is None for row in mine),
                         "holiday_days": sorted(Counter(row["timestamp_local"][:10] for row in mine
                                                        if row["is_public_holiday"]))}
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for site, info in summary.items():
        print(f"{site:13s} hours {info['hours']:5d} | weekend {info['weekend_hours']:5d} | "
              f"public holiday {info['public_holiday_hours']:4d} ({len(info['holiday_days'])} days) | "
              f"unknown {info['holiday_unknown_hours']}")
    print(f"Wrote {args.output_dir / 'hourly_calendar.csv'} and summary.json")

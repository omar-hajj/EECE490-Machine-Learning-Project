"""The public holiday file and the quiet-day comparison."""

from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.data.calendar_days import build_calendar_table, calendar_columns, load_public_holidays
from lebanon_energy.data.data_checks import holidays_versus_quiet_days, quiet_weekdays

HEADER = "date,name,source,source_url,confidence,note\n"


def write(text):
    folder = tempfile.mkdtemp()
    path = Path(folder) / "holidays.csv"
    path.write_text(HEADER + text, encoding="utf-8")
    return path


class HolidayFileTests(unittest.TestCase):
    def test_project_file_loads_with_sources(self):
        holidays = load_public_holidays()
        self.assertIn(date(2026, 5, 27), holidays)
        self.assertTrue(all(row["source_url"].startswith("http") for row in holidays.values()))

    def test_duplicate_date_is_refused(self):
        row = "2026-05-01,Labor Day,list,https://example.org,high,\n"
        with self.assertRaises(ValueError):
            load_public_holidays(write(row + row))

    def test_unsourced_or_unknown_confidence_is_refused(self):
        for row in ("2026-05-01,Labor Day,list,,high,\n", "2026-05-01,Labor Day,list,https://example.org,maybe,\n"):
            with self.subTest(row=row), self.assertRaises(ValueError):
                load_public_holidays(write(row))


class CalendarColumnTests(unittest.TestCase):
    holidays = load_public_holidays()

    def test_eid_hour(self):
        columns = calendar_columns(datetime(2026, 5, 27, 9), self.holidays)
        self.assertEqual((columns["weekday"], columns["is_weekend"], columns["is_public_holiday"]), ("Wednesday", False, True))
        self.assertEqual(columns["public_holiday_name"], "Eid al-Adha")

    def test_ordinary_saturday(self):
        columns = calendar_columns(datetime(2026, 6, 6, 14), self.holidays)
        self.assertTrue(columns["is_weekend"])
        self.assertFalse(columns["is_public_holiday"])
        self.assertIsNone(columns["is_school_holiday"])  # unknown until Azm's calendar arrives

    def test_outside_researched_periods_is_unknown_not_a_working_day(self):
        self.assertIsNone(calendar_columns(datetime(2024, 10, 15, 9), self.holidays)["is_public_holiday"])

    def test_table_has_one_row_per_site_hour(self):
        path = Path(tempfile.mkdtemp()) / "hourly.csv"
        path.write_text("site_id,timestamp_local_unverified,target\n"
                        "azm,2026-05-01T10:00:00,load\nazm,2026-05-01T10:00:00,pv\nazm,2026-05-04T10:00:00,load\n",
                        encoding="utf-8")
        rows = build_calendar_table(path, self.holidays)
        self.assertEqual([(r["timestamp_local"], r["is_public_holiday"]) for r in rows],
                         [("2026-05-01T10:00:00", True), ("2026-05-04T10:00:00", False)])


class QuietDayTests(unittest.TestCase):
    def test_holiday_is_quiet_and_extra_quiet_day_is_reported(self):
        hours = {}
        for week in range(4):
            for weekday in range(5):
                day = datetime(2026, 6, 1) + timedelta(days=7 * week + weekday)  # June 1, 2026 is a Monday
                load = 300.0
                if day.date() in (date(2026, 6, 16), date(2026, 6, 23)):  # two quiet Tuesdays
                    load = 90.0
                for hour in range(8, 16):
                    hours[day.replace(hour=hour)] = load
        daily, quiet = quiet_weekdays(hours)
        self.assertEqual([q["date"] for q in quiet], ["2026-06-16", "2026-06-23"])
        result = holidays_versus_quiet_days(daily, quiet, {date(2026, 6, 16): {"name": "Hijri New Year", "confidence": "medium"}})
        self.assertEqual(result["official_holidays_that_were_quiet"], 1)
        self.assertEqual([q["date"] for q in result["quiet_days_not_official_holidays"]], ["2026-06-23"])


if __name__ == "__main__":
    unittest.main()

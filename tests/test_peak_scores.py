"""Daily peak error (roadmap "peak error")."""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.evaluation.metrics import daily_peak_scores


def day(start, actual_peak_hour, actual_peak, forecast_peak_hour, forecast_peak, base=100.0):
    rows = []
    for hour in range(24):
        stamp = start + timedelta(hours=hour)
        actual = actual_peak if hour == actual_peak_hour else base
        forecast = forecast_peak if hour == forecast_peak_hour else base
        rows.append((stamp, actual, forecast))
    return rows


class DailyPeakTests(unittest.TestCase):
    def test_under_forecast_and_late_peak(self):
        rows = day(datetime(2026, 8, 3), 9, 300.0, 11, 250.0)       # 50 kW too low, 2 hours late
        result = daily_peak_scores(rows)
        self.assertEqual(result["mean_absolute_peak_error"], 50.0)
        self.assertEqual(result["largest_peak_error"], -50.0)
        self.assertEqual((result["under_forecast_days"], result["mean_peak_hour_offset"]), (1, 2.0))

    def test_incomplete_day_is_skipped(self):
        complete = day(datetime(2026, 8, 3), 9, 300.0, 9, 320.0)
        partial = day(datetime(2026, 8, 4), 9, 300.0, 9, 100.0)[:20]   # afternoon missing
        result = daily_peak_scores(complete + partial)
        self.assertEqual((result["complete_days"], result["days_skipped_incomplete"]), (1, 1))
        self.assertEqual(result["under_forecast_days"], 0)

    def test_no_complete_day_is_an_error(self):
        with self.assertRaises(ValueError):
            daily_peak_scores(day(datetime(2026, 8, 3), 9, 300.0, 9, 300.0)[:23])


if __name__ == "__main__":
    unittest.main()

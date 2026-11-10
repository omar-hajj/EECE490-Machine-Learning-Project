"""Checks for hourly completeness, forecast timing and fair comparisons."""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.data.preparation import hourly_means
from lebanon_energy.models.baselines import evaluate_series, fit_weekday_profile, predict


class HourlyPreparationTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2025, 6, 1)
        self.cutoff = datetime(2025, 7, 1)

    def prepare(self, records, interval=30, targets=("load", "pv")):
        return hourly_means(records, targets=targets, sampling_minutes=interval, cutoff=self.cutoff)

    def test_hourly_means_do_not_fill_incomplete_hours(self):
        records = [(self.start, {"load": 100, "pv": 10}),
                   (self.start + timedelta(minutes=30), {"load": 120, "pv": 30}),
                   (self.start + timedelta(hours=1), {"load": 200, "pv": 20})]
        hourly, report = self.prepare(records)
        self.assertEqual(hourly["load"], {self.start: 110})
        self.assertEqual(hourly["pv"], {self.start: 20})
        self.assertEqual(report["retained_hours_by_target"]["load"], 1)

    def test_bad_pv_does_not_remove_valid_load_and_zero_is_preserved(self):
        hourly, _ = self.prepare([(self.start, {"load": 0, "pv": None}),
                                  (self.start + timedelta(minutes=30), {"load": 0, "pv": 10})])
        self.assertEqual(hourly["load"][self.start], 0)
        self.assertEqual(hourly["pv"], {})

    def test_two_readings_in_same_slot_do_not_count_as_complete(self):
        hourly, _ = self.prepare([(self.start, {"load": 100}),
                                  (self.start + timedelta(minutes=10), {"load": 120})], targets=("load",))
        self.assertEqual(hourly["load"], {})

    def test_azm_requires_all_twelve_readings(self):
        records = [(self.start + timedelta(minutes=5 * index), {"load": index}) for index in range(12)]
        complete, _ = self.prepare(records, interval=5, targets=("load",))
        incomplete, _ = self.prepare(records[:-1], interval=5, targets=("load",))
        self.assertEqual(complete["load"][self.start], 5.5)
        self.assertEqual(incomplete["load"], {})

    def test_duplicate_timestamps_are_not_silently_averaged(self):
        with self.assertRaisesRegex(ValueError, "Repeated"):
            self.prepare([(self.start, {"load": 1}), (self.start, {"load": 2})])

    def test_test_period_is_excluded_before_values_are_read(self):
        hourly, report = self.prepare([(self.cutoff, {"load": object(), "pv": object()})])
        self.assertEqual(hourly, {"load": {}, "pv": {}})
        self.assertEqual(report["reserved_or_later_raw_records_excluded"], 1)


class ForecastIntegrityTests(unittest.TestCase):
    def test_weekday_profile_uses_training_only(self):
        start = datetime(2025, 6, 2)
        series = {datetime(2025, 5, 26, 10): 100, datetime(2025, 6, 2, 10): 99999}
        profile = fit_weekday_profile(series, start)
        forecast, available_at = predict(series, profile, datetime(2025, 6, 2, 10), "weekday_average")
        self.assertEqual(forecast, 100)
        self.assertLessEqual(available_at, start)

    def test_lag_does_not_jump_over_a_missing_week(self):
        timestamp = datetime(2025, 6, 1)
        series = {timestamp - timedelta(days=14): 100}
        self.assertIsNone(predict(series, {}, timestamp, "last_week"))

    def test_last_hour_yesterday_is_available_at_midnight(self):
        timestamp = datetime(2025, 6, 2, 23)
        series = {datetime(2025, 6, 1, 23): 100}
        self.assertEqual(predict(series, {}, timestamp, "yesterday"), (100, datetime(2025, 6, 2)))

    def test_future_profile_is_rejected(self):
        timestamp = datetime(2025, 6, 2, 10)
        profile = {(timestamp.weekday(), timestamp.hour): (100, timestamp)}
        with self.assertRaisesRegex(ValueError, "midnight"):
            predict({}, profile, timestamp, "weekday_average")

    def test_methods_are_compared_on_identical_observations(self):
        start = datetime(2025, 6, 1)
        series = {start: 10, start + timedelta(hours=1): 20,
                  start - timedelta(days=1): 10,
                  start - timedelta(days=1) + timedelta(hours=1): 20,
                  start - timedelta(days=7) + timedelta(hours=1): 10}
        summary, rows = evaluate_series(series, start=start, end=start + timedelta(days=1))
        self.assertEqual(summary["common_scored_hours"], 1)
        self.assertEqual(summary["methods"]["yesterday"]["scored_hours"], 2)
        for method in summary["methods"].values():
            self.assertEqual(method["common_hours_scores"]["observations"], 1)
            self.assertEqual(method["common_hours_scores"]["mean_actual"], 20)
        self.assertEqual(summary["missing_actual_hours"], 22)
        self.assertEqual(len(rows), 24)

    def test_same_day_future_measurements_cannot_change_predictions(self):
        start = datetime(2025, 6, 1)
        series = {start - timedelta(days=1): 10, start: 20, start + timedelta(hours=10): 30}
        _, before = evaluate_series(series, start=start, end=start + timedelta(days=1))
        series[start + timedelta(hours=10)] = 99999
        _, after = evaluate_series(series, start=start, end=start + timedelta(days=1))
        self.assertEqual([row["predictions"] for row in before], [row["predictions"] for row in after])


if __name__ == "__main__":
    unittest.main()

"""Weather interval alignment and explicit nominal-availability limits."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.weather import VARIABLES, aligned_features
from lebanon_energy.ridge import model_features


class WeatherAlignmentTests(unittest.TestCase):
    def source(self, target):
        # Beirut is UTC+3 in this July example. Distinct values in adjacent
        # hours reveal accidental use of one timestamp for every variable.
        start_utc = target.replace(tzinfo=timezone(timedelta(hours=3))).astimezone(timezone.utc)
        values = {start_utc: {name: 10. for name in VARIABLES},
                  start_utc + timedelta(hours=1): {name: 20. for name in VARIABLES}}
        return values

    def test_instant_values_use_start_and_radiation_uses_end(self):
        target = datetime(2026, 7, 1, 12)
        row = aligned_features(self.source(target), target)
        self.assertEqual(row["features"]["forecast_temperature"], 10.)
        self.assertEqual(row["features"]["forecast_shortwave_radiation"], 20.)
        self.assertEqual(row["nominal_available_at_local"], datetime(2026, 6, 30, 13))
        self.assertEqual(row["nominal_margin_hours"], 11)

    def test_last_hour_nominally_arrives_at_issue_time_but_is_not_verified(self):
        target = datetime(2026, 7, 1, 23)
        row = aligned_features(self.source(target), target)
        self.assertEqual(row["nominal_available_at_local"], datetime(2026, 7, 1))
        self.assertEqual(row["nominal_margin_hours"], 0)
        self.assertFalse(row["publication_availability_verified"])

    def test_missing_radiation_endpoint_is_not_filled(self):
        target = datetime(2026, 7, 1, 12)
        source = self.source(target)
        del source[max(source)]
        self.assertIsNone(aligned_features(source, target))

    def test_nonexistent_local_hour_needs_explicit_resolution(self):
        with self.assertRaisesRegex(ValueError, "Ambiguous/nonexistent"):
            aligned_features({}, datetime(2026, 3, 29, 0))

    def test_nominal_weather_after_midnight_cannot_enter_features(self):
        target = datetime(2026, 7, 1, 12)
        history = {target - timedelta(hours=24): 10., target - timedelta(hours=168): 20.}
        weather = {target: {"features": {"forecast_temperature": 30.}, "available_at": datetime(2026, 7, 1, 1)}}
        with self.assertRaisesRegex(ValueError, "midnight"):
            model_features(history, target, (24, 168), weather)


if __name__ == "__main__":
    unittest.main()

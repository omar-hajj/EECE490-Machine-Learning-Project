"""Feature timing and training-only preprocessing checks for Ridge."""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.features import history_calendar_features
from lebanon_energy.ridge import build_rows, make_pipeline


class HistoryFeatureTests(unittest.TestCase):
    def test_exact_lags_and_availability(self):
        target = datetime(2026, 8, 2, 23)
        values = {target - timedelta(hours=24): 10, target - timedelta(hours=168): 20}
        features, available_at = history_calendar_features(values, target)
        self.assertEqual(features["lag_24h"], 10)
        self.assertEqual(features["lag_168h"], 20)
        self.assertEqual(available_at, datetime(2026, 8, 2))

    def test_missing_week_is_not_imputed(self):
        target = datetime(2026, 8, 2, 10)
        values = {target - timedelta(hours=24): 10, target - timedelta(hours=169): 20}
        self.assertEqual(history_calendar_features(values, target), (None, None))

    def test_current_and_future_actuals_do_not_change_features(self):
        target = datetime(2026, 8, 2, 10)
        values = {target - timedelta(hours=24): 10, target - timedelta(hours=168): 20}
        before = history_calendar_features(values, target)
        values[target] = 999999
        values[target + timedelta(hours=1)] = 1000000
        self.assertEqual(history_calendar_features(values, target), before)

    def test_lags_unavailable_at_midnight_are_rejected(self):
        target = datetime(2026, 8, 2, 10)
        with self.assertRaisesRegex(ValueError, "midnight"):
            history_calendar_features({target - timedelta(hours=1): 10}, target, (1,))

    def test_validation_values_never_enter_training_rows(self):
        start = datetime(2026, 8, 1)
        first = start - timedelta(days=14)
        series = {first + timedelta(hours=hour): float(hour) for hour in range(15 * 24)}
        training, validation = build_rows(series, start, start + timedelta(days=1), (24, 168))
        self.assertTrue(training)
        self.assertTrue(all(row["timestamp"] < start for row in training))
        self.assertTrue(all(row["available_at"] <= row["timestamp"].replace(hour=0) for row in training))
        self.assertEqual(len(validation), 24)

    def test_preprocessor_is_fitted_only_on_supplied_training_rows(self):
        model = make_pipeline(1.0)
        training = [{"hour_of_week": "0", "lag_24h": 10., "lag_168h": 20.},
                    {"hour_of_week": "1", "lag_24h": 30., "lag_168h": 40.}]
        model.fit(training, [15., 35.])
        vectorizer = model.named_steps["vectorizer"]
        scaler = model.named_steps["scaler"]
        index = list(vectorizer.get_feature_names_out()).index("lag_24h")
        self.assertEqual(scaler.mean_[index], 20.)
        model.predict([{"hour_of_week": "2", "lag_24h": 99999., "lag_168h": 99999.}])
        self.assertEqual(scaler.mean_[index], 20.)


if __name__ == "__main__":
    unittest.main()

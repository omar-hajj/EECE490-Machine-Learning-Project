"""Chapter 6 metrics (regression, confusion matrix, McNemar, Z-test) and the tuning helpers."""
from datetime import date, datetime, timedelta
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.evaluation.course_metrics import (
    confusion, mcnemar, paired_error_z_test, proportion_z_test, regression_metrics)
from lebanon_energy.models.tuning import choose_sizing, extra_features, fold_scores

MONDAY = datetime(2026, 6, 8)


class RegressionMetricTests(unittest.TestCase):
    def test_values_and_sign_convention(self):
        scores = regression_metrics([10.0, 20.0, 30.0], [8.0, 20.0, 26.0])
        self.assertAlmostEqual(scores["mbe"], 2.0)       # actual - forecast > 0: under-prediction
        self.assertAlmostEqual(scores["mae"], 2.0)
        self.assertAlmostEqual(scores["mse"], 20 / 3)
        self.assertAlmostEqual(scores["rmse"], math.sqrt(20 / 3))
        self.assertAlmostEqual(scores["nmae"], 0.1)
        self.assertIsNone(regression_metrics([], []))


class ClassificationMetricTests(unittest.TestCase):
    def test_confusion_matrix_precision_recall_f1(self):
        needed = ["small"] * 6 + ["large"] * 4
        picked = ["small"] * 4 + ["large"] * 2 + ["large"] * 3 + ["small"]
        result = confusion(needed, picked, ["small", "large"])
        self.assertEqual(result["matrix"], [[4, 2], [1, 3]])
        self.assertAlmostEqual(result["accuracy"], 0.7)
        self.assertAlmostEqual(result["per_class"]["small"]["precision"], 4 / 5)
        self.assertAlmostEqual(result["per_class"]["small"]["recall"], 4 / 6)
        self.assertAlmostEqual(result["per_class"]["large"]["precision"], 3 / 5)
        self.assertAlmostEqual(result["per_class"]["large"]["recall"], 3 / 4)
        self.assertAlmostEqual(result["macro_recall"], (4 / 6 + 3 / 4) / 2)
        self.assertAlmostEqual(result["below_needed"], 0.1)   # needed large, picked small
        self.assertAlmostEqual(result["above_needed"], 0.2)

    def test_classes_never_needed_are_left_out_of_macro_averages(self):
        result = confusion(["a", "a"], ["a", "b"], ["a", "b"])
        self.assertIsNone(result["per_class"]["b"]["recall"])
        self.assertAlmostEqual(result["macro_recall"], 0.5)


class StatisticalTestTests(unittest.TestCase):
    def test_mcnemar_matches_the_notes_example(self):
        # Notes: B = 11, C = 1 strongly suggests model 1 is better; chi2 = (11 - 1)^2 / 12.
        first = [True] * 11 + [False] * 1 + [True] * 20
        second = [False] * 11 + [True] * 1 + [True] * 20
        result = mcnemar(first, second)
        self.assertEqual((result["only_first_correct_B"], result["only_second_correct_C"]), (11, 1))
        self.assertAlmostEqual(result["chi_square"], 100 / 12)
        self.assertLess(result["p_value"], 0.01)
        same = mcnemar([True, False], [True, False])
        self.assertEqual((same["chi_square"], same["p_value"]), (0.0, 1.0))

    def test_proportion_z_test_formula(self):
        result = proportion_z_test(0.9, 0.8, 100)
        expected = 0.1 / math.sqrt(0.9 * 0.1 / 100 + 0.8 * 0.2 / 100)
        self.assertAlmostEqual(result["z"], expected)
        self.assertAlmostEqual(proportion_z_test(0.8, 0.8, 100)["p_value_two_sided"], 1.0)

    def test_paired_error_test_sign(self):
        actual = [100.0] * 50
        better = [99.0 + (i % 2) for i in range(50)]
        worse = [90.0 + (i % 3) for i in range(50)]
        result = paired_error_z_test(actual, better, worse)
        self.assertLess(result["mean_difference_kw"], 0)
        self.assertLess(result["p_value_two_sided"], 0.001)


class TuningHelperTests(unittest.TestCase):
    def setUp(self):
        self.series = {MONDAY - timedelta(days=14) + timedelta(hours=h): float(h) for h in range(14 * 24)}

    def test_similar_day_on_monday_is_friday_and_never_today(self):
        stamp = MONDAY.replace(hour=9)
        values = extra_features(self.series, stamp, set(), ("similar_day_same_hour",))
        self.assertEqual(values["similar_day_same_hour"], self.series[stamp - timedelta(days=3)])
        saturday = stamp - timedelta(days=2)
        values = extra_features(self.series, saturday, set(), ("similar_day_same_hour",))
        self.assertEqual(values["similar_day_same_hour"], self.series[saturday - timedelta(days=6)])  # the Sunday before
        # A holiday on Friday is a day off, so Monday falls back to Thursday.
        values = extra_features(self.series, stamp, {date(2026, 6, 5)}, ("similar_day_same_hour",))
        self.assertEqual(values["similar_day_same_hour"], self.series[stamp - timedelta(days=4)])

    def test_extras_use_only_completed_hours_and_report_gaps(self):
        stamp = MONDAY.replace(hour=9)
        names = ("lag_48h", "yesterday_mean", "yesterday_max", "week_mean_same_hour", "similar_day_same_hour")
        before = extra_features(self.series, stamp, set(), names)
        polluted = {**self.series, **{MONDAY + timedelta(hours=h): 9999.0 for h in range(48)}}
        self.assertEqual(extra_features(polluted, stamp, set(), names), before)
        self.assertIsNone(extra_features({}, stamp, set(), ("lag_48h",)))
        with self.assertRaises(ValueError):
            extra_features(self.series, stamp, set(), ("unknown",))

    def test_fold_scores(self):
        series = {MONDAY + timedelta(hours=h): 10.0 for h in range(48)}
        predictions = {s: 12.0 if s < MONDAY + timedelta(days=1) else 14.0 for s in series}
        folds = {"first": (MONDAY, MONDAY + timedelta(days=1)), "second": (MONDAY + timedelta(days=1), MONDAY + timedelta(days=2))}
        scores = fold_scores(series, predictions, sorted(series), folds)
        self.assertEqual(scores["fold_mae"], {"first": 2.0, "second": 4.0})
        self.assertEqual((scores["mean_fold_mae"], scores["fold_spread"]), (3.0, 2.0))

    def test_sizing_choice_never_gives_up_safety(self):
        setting = lambda q, w, r, under, over: {"quantile": q, "window_days": w, "reserve": r,
                                                "undersized": under, "oversized": over}
        sweep = [setting(0.9, 28, 0.1, 10, 400), setting(0.8, 7, 0.0, 30, 100), setting(0.9, 14, 0.05, 10, 350),
                 setting(0.95, 28, 0.1, 8, 500)]
        reference, chosen = choose_sizing(sweep, {"quantile": 0.9, "window_days": 28, "reserve": 0.1})
        self.assertEqual(reference["oversized"], 400)
        self.assertEqual((chosen["quantile"], chosen["window_days"], chosen["oversized"]), (0.9, 14, 350))


class TransferTestGuardTests(unittest.TestCase):
    def test_refuses_a_second_run_before_reading_any_data(self):
        import tempfile
        from unittest.mock import patch
        from lebanon_energy.evaluation import transfer_test

        with tempfile.TemporaryDirectory() as folder:
            record = Path(folder) / "final_test_household_3.json"
            record.write_text("{}", encoding="utf-8")
            with patch.object(transfer_test, "RECORD", record), \
                    patch.object(sys, "argv", ["transfer_test.py", "--archive", "missing.zip", "--open-test-set"]), \
                    patch.object(transfer_test, "read_load", side_effect=AssertionError("must not read data")):
                with self.assertRaises(SystemExit) as raised:
                    transfer_test.main()
        self.assertIn("already opened", str(raised.exception))

    def test_selection_ignores_everything_from_the_test_month_on(self):
        from lebanon_energy.evaluation.transfer_test import select

        start = datetime(2026, 3, 2)
        series = {start + timedelta(hours=h): 100.0 + 20 * ((h % 24) in range(8, 18)) + (h % 7) for h in range(60 * 24)}
        end = start + timedelta(days=45)
        polluted = {**series, **{s: 9999.0 for s in series if s >= end}}
        first_day = start + timedelta(days=16)
        self.assertEqual(select(series, set(), first_day, end)[0], select(polluted, set(), first_day, end)[0])


if __name__ == "__main__":
    unittest.main()

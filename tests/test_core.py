"""Tests for evaluation integrity, source dates and capacity constraints."""

from datetime import datetime
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.audit import parse_timestamp
from lebanon_energy.evaluation import compare_modes, score
from lebanon_energy.generators import Generator, recommend


class EvaluationTests(unittest.TestCase):
    def test_normalized_error_is_scale_invariant(self):
        self.assertAlmostEqual(score([10, 30], [12, 26]).nmae, 0.15)
        self.assertAlmostEqual(score([10000, 30000], [12000, 26000]).nmae, 0.15)

    def test_zero_target_does_not_report_perfect_normalized_accuracy(self):
        self.assertIsNone(score([0, 0], [0, 1]).nmae)
        self.assertEqual(compare_modes([0], [0], [0])["status"], "undefined_normalization")

    def test_missing_or_misaligned_predictions_are_rejected(self):
        for actual, predicted in (([1, 2], [1]), ([], []), ([1], [math.nan]), ([-1], [1])):
            with self.subTest(actual=actual, predicted=predicted), self.assertRaises(ValueError):
                score(actual, predicted)

    def test_no_automatic_acceptance_without_thresholds(self):
        result = compare_modes([100], [100], [100])
        self.assertEqual(result["status"], "awaiting_acceptance_thresholds")
        self.assertFalse(result["deployment_approved"])

    def test_both_absolute_and_relative_limits_are_required(self):
        result = compare_modes([100], [101], [108], maximum_nmae=0.10, maximum_nmae_gap=0.02)
        self.assertEqual(result["status"], "does_not_meet_numeric_limits")
        self.assertAlmostEqual(result["nmae_gap"], 0.07)


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.units = [Generator("small", 100), Generator("large", 200)]

    def test_margin_can_change_required_unit(self):
        result = recommend(95, self.units, allowed_configurations=[("small",), ("large",)], reserve_margin_fraction=0.10)
        self.assertEqual(result["candidate_configurations"], [["large"]])

    def test_infeasible_load_is_flagged_without_undersized_recommendation(self):
        result = recommend(250, self.units, allowed_configurations=[("small",), ("large",)], reserve_margin_fraction=0)
        self.assertEqual(result["status"], "insufficient_available_capacity")
        self.assertEqual(result["candidate_configurations"], [])

    def test_parallel_operation_requires_explicit_permission(self):
        result = recommend(250, self.units, allowed_configurations=[("small", "large")], reserve_margin_fraction=0)
        self.assertEqual(result["selected_capacity_kw"], 300)

    def test_unavailable_generator_is_not_recommended(self):
        units = [Generator("small", 100), Generator("large", 200, available=False)]
        result = recommend(150, units, allowed_configurations=[("small",), ("large",)], reserve_margin_fraction=0)
        self.assertEqual(result["candidate_configurations"], [])

    def test_equal_capacity_units_remain_operator_choices(self):
        result = recommend(50, [Generator("a", 100), Generator("b", 100)], allowed_configurations=[("b",), ("a",)], reserve_margin_fraction=0)
        self.assertEqual(result["candidate_configurations"], [["a"], ["b"]])

    def test_unknown_or_duplicated_equipment_is_rejected(self):
        for configuration in (("unknown",), ("small", "small")):
            with self.subTest(configuration=configuration), self.assertRaises(ValueError):
                recommend(50, self.units, allowed_configurations=[configuration], reserve_margin_fraction=0)


class TimestampTests(unittest.TestCase):
    def test_ambiguous_dates_are_not_guessed(self):
        self.assertEqual(parse_timestamp("02/01/2025 00:00"), (None, "ambiguous"))

    def test_filename_month_can_resolve_both_conventions(self):
        self.assertEqual(parse_timestamp("02/01/2025 00:00", 1)[0], datetime(2025, 1, 2))
        self.assertEqual(parse_timestamp("02/01/2025 00:00", 2)[0], datetime(2025, 2, 1))

    def test_timezone_offset_is_preserved(self):
        parsed, _ = parse_timestamp("2026-07-01T09:00:00+03:00")
        self.assertEqual(parsed.utcoffset().total_seconds(), 10800)


if __name__ == "__main__":
    unittest.main()

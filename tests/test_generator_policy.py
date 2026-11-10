"""Observed-capacity extraction, draft policy and wrong-generator-hours metric."""

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.generators.capacity import draft_policy, hourly_generator_table, summarize
from lebanon_energy.evaluation.generator_choice import net_from_targets, score_methods
from lebanon_energy.generators.policy import Generator, choice_errors, load_policy

UNITS = [Generator("small", 100), Generator("medium", 200), Generator("large", 400)]
ALLOWED = [["small"], ["medium"], ["large"], ["medium", "large"]]


def _records(start, hours, running, kw, load=120.0, pv=20.0):
    """Five-minute rows where only `running` reports status 1 at `kw`."""
    rows = []
    for step in range(hours * 12):
        values = {"load": load, "pv": pv, "utility_kw": 0.0, "utility_status": 0.0}
        for g in ("G1", "G2"):
            on = g in running
            values[f"{g}_kw"] = kw if on else 0.0
            values[f"{g}_status"] = 1.0 if on else 0.0
        rows.append((start + timedelta(minutes=5 * step), values))
    return rows


class ChoiceErrorTests(unittest.TestCase):
    def test_right_sized_when_forecast_matches_need(self):
        result = choice_errors([80, 150, 350], [80, 150, 350], UNITS,
                               allowed_configurations=ALLOWED, reserve_margin_fraction=0.0)
        self.assertEqual(result["right_sized_hours"], 3)
        self.assertEqual(result["undersized_hours"] + result["oversized_hours"], 0)

    def test_underforecast_is_overload_risk(self):
        # Actual 150 kW needs "medium"; a 90 kW forecast picks "small" (100 kW).
        result = choice_errors([150], [90], UNITS, allowed_configurations=ALLOWED, reserve_margin_fraction=0.0)
        self.assertEqual(result["undersized_hours"], 1)
        self.assertAlmostEqual(result["shortfall_kwh"], 50)

    def test_margin_can_cause_oversizing(self):
        # Actual 95 kW fits "small"; 95 x 1.1 = 104.5 kW forces "medium".
        result = choice_errors([95], [95], UNITS, allowed_configurations=ALLOWED, reserve_margin_fraction=0.10)
        self.assertEqual(result["oversized_hours"], 1)
        self.assertAlmostEqual(result["excess_capacity_kwh"], 100)

    def test_negative_net_load_treated_as_zero(self):
        result = choice_errors([-10], [-30], UNITS, allowed_configurations=ALLOWED, reserve_margin_fraction=0.1)
        self.assertEqual(result["right_sized_hours"], 1)

    def test_need_above_all_capacity_counts_as_undersized_and_infeasible(self):
        result = choice_errors([700], [300], UNITS, allowed_configurations=ALLOWED, reserve_margin_fraction=0.0)
        self.assertEqual(result["infeasible_actual_hours"], 1)
        self.assertEqual(result["undersized_hours"], 1)

    def test_rejects_misaligned_inputs(self):
        with self.assertRaises(ValueError):
            choice_errors([1, 2], [1], UNITS, allowed_configurations=ALLOWED, reserve_margin_fraction=0)


class CapacityExtractionTests(unittest.TestCase):
    def setUp(self):
        start = datetime(2026, 5, 4)
        self.records = (_records(start, 5, {"G1"}, 90.0)
                        + _records(start + timedelta(hours=5), 3, {"G1", "G2"}, 150.0, load=320.0)
                        + _records(start + timedelta(hours=8), 1, {"G2"}, 180.0))
        # A five-minute handover overlap must not count as deliberate parallel running.
        self.records[-1][1]["G1_status"] = 1.0

    def test_observed_maximum_and_whole_hour_usage(self):
        summary = summarize(self.records, generator_ids=("G1", "G2"))
        units = {unit["generator_id"]: unit for unit in summary["units"]}
        self.assertEqual(units["G1"]["observed_max_kw"], 150.0)
        self.assertEqual(units["G2"]["observed_max_kw"], 180.0)
        usage = {entry["configuration"]: entry["whole_hours"] for entry in summary["configurations"]}
        self.assertEqual(usage, {"G1": 5, "G1+G2": 3})
        self.assertEqual(summary["whole_single_configuration_hours"], 8)

    def test_draft_policy_keeps_only_sustained_parallel_combinations(self):
        summary = summarize(self.records, generator_ids=("G1", "G2"))
        self.assertIn(["G1", "G2"], draft_policy(summary, minimum_whole_hours=3)["allowed_configurations"])
        self.assertNotIn(["G1", "G2"], draft_policy(summary, minimum_whole_hours=4)["allowed_configurations"])

    def test_policy_round_trip(self):
        policy = draft_policy(summarize(self.records, generator_ids=("G1", "G2")))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "policy.json"
            path.write_text(json.dumps(policy), encoding="utf-8")
            generators, allowed, margin = load_policy(path)
        self.assertEqual([g.generator_id for g in generators], ["G1", "G2"])
        self.assertEqual(margin, 0.10)
        self.assertEqual(allowed[:2], [["G1"], ["G2"]])


class HourlyGeneratorTableTests(unittest.TestCase):
    def test_steady_handover_and_incomplete_hours(self):
        start = datetime(2026, 5, 4, 8)
        steady = _records(start, 1, {"G1"}, 90.0)
        handover = _records(start + timedelta(hours=1), 1, {"G1"}, 90.0)
        for _, values in handover[6:]:          # G2 takes over for the second half hour
            values.update({"G1_kw": 0.0, "G1_status": 0.0, "G2_kw": 150.0, "G2_status": 1.0})
        incomplete = _records(start + timedelta(hours=2), 1, {"G2"}, 150.0)[:11]
        rows, excluded = hourly_generator_table(steady + handover + incomplete, generator_ids=("G1", "G2"))
        self.assertEqual([r["configuration"] for r in rows], ["G1", "mixed"])
        self.assertEqual((rows[1]["G1_running_share"], rows[1]["G2_running_share"]), (0.5, 0.5))
        self.assertAlmostEqual(rows[1]["G2_kw"], 75.0)
        self.assertEqual(excluded, {"incomplete_or_repeated_sampling_slots": 1})


class MethodComparisonTests(unittest.TestCase):
    def test_methods_scored_on_shared_hours_only(self):
        t0, t1 = datetime(2026, 8, 3, 9), datetime(2026, 8, 3, 10)
        actual = net_from_targets({t0: {"load": 150, "pv": 30}, t1: {"load": 90, "pv": 0}})
        forecasts = {"a": {t0: 120, t1: 90}, "b": {t0: 60}}
        hours, results = score_methods(forecasts, actual, UNITS, ALLOWED, 0.0)
        self.assertEqual(hours, [t0])
        self.assertEqual(results["a"]["right_sized_hours"], 1)
        self.assertEqual(results["b"]["undersized_hours"], 1)


if __name__ == "__main__":
    unittest.main()

"""Frozen-meter masking used for Household 3 (decision of 2026-11-10)."""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.data.preparation import hourly_means, mask_frozen_readings

TARGETS = {"load": "Load power (w)", "pv": "PV power (w)"}
START = datetime(2025, 4, 4, 18, 0)


def rows(values, start=START):
    return [(start + timedelta(minutes=30 * i), {"load": load, "pv": pv}) for i, (load, pv) in enumerate(values)]


def mask(records, minimum=6):
    return mask_frozen_readings(records, targets=TARGETS, sampling_minutes=30, minimum_consecutive_readings=minimum)


class FrozenReadingTests(unittest.TestCase):
    def test_six_identical_nonzero_readings_are_masked(self):
        records = rows([(90, 5)] + [(137, 0)] * 6 + [(11, 1)])
        cleaned, stretches = mask(records)
        self.assertEqual(len(stretches), 1)
        self.assertEqual(stretches[0]["readings"], 6)
        self.assertEqual([v["load"] for _, v in cleaned], [90] + [None] * 6 + [11])

    def test_five_identical_readings_are_kept(self):
        _, stretches = mask(rows([(137, 0)] * 5 + [(11, 1)]))
        self.assertEqual(stretches, [])

    def test_all_zero_stretch_is_kept(self):
        # e.g. an outage at night: no load, no solar
        _, stretches = mask(rows([(0, 0)] * 10))
        self.assertEqual(stretches, [])

    def test_one_channel_changing_means_not_frozen(self):
        # the December pattern: one value steady, the others still moving
        _, stretches = mask(rows([(0.0056 * (i % 3 + 1), 0) for i in range(12)]))
        self.assertEqual(stretches, [])

    def test_time_gap_breaks_a_stretch(self):
        first = rows([(137, 0)] * 3)
        second = rows([(137, 0)] * 3, start=START + timedelta(hours=5))
        _, stretches = mask(first + second)
        self.assertEqual(stretches, [])

    def test_masked_hours_are_dropped_by_the_complete_hour_rule(self):
        records = rows([(100, 1), (100, 2)] + [(137, 0)] * 6 + [(50, 3), (60, 4)])
        cleaned, _ = mask(records)
        hourly, report = hourly_means(cleaned, targets=TARGETS, sampling_minutes=30, cutoff=datetime(2026, 1, 1))
        self.assertEqual(sorted(hourly["load"]), [START, START + timedelta(hours=4)])
        self.assertEqual(report["exclusions_by_target"]["load"]["missing_nonnumeric_nonfinite_or_negative_value"], 3)


if __name__ == "__main__":
    unittest.main()

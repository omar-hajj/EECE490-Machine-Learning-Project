"""The three data checks behind DATA_PROVENANCE.md, on small made-up data."""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.data.data_checks import compare_village_sites, count_jumps, power_balance, stuck_runs

MONDAY_5AM = datetime(2026, 6, 8, 5, 0)


def five_minute_hour(start, load, pv=0.0, generators=None):
    return [(start + timedelta(minutes=5 * i), load, pv, load - pv if generators is None else generators)
            for i in range(12)]


class JumpTests(unittest.TestCase):
    def test_real_morning_jump_is_counted_and_confirmed(self):
        readings = five_minute_hour(MONDAY_5AM, 100) + five_minute_hour(MONDAY_5AM + timedelta(hours=1), 350)
        result = count_jumps(readings)
        self.assertEqual(result["summary"]["count"], 1)
        self.assertEqual(result["summary"]["confirmed_by_generator_meters"], 1)
        self.assertEqual(result["main_definition_jumps"][0]["weekday"], "Monday")

    def test_meter_error_is_not_confirmed(self):
        # load jumps but the generators keep producing 100 kW
        readings = (five_minute_hour(MONDAY_5AM, 100)
                    + five_minute_hour(MONDAY_5AM + timedelta(hours=1), 350, generators=100))
        self.assertEqual(count_jumps(readings)["summary"]["confirmed_by_generator_meters"], 0)

    def test_gap_between_hours_is_not_a_jump(self):
        readings = five_minute_hour(MONDAY_5AM, 100) + five_minute_hour(MONDAY_5AM + timedelta(hours=3), 350)
        result = count_jumps(readings)
        self.assertEqual(result["summary"]["count"], 0)
        self.assertEqual(result["definitions"]["hourly mean vs previous available hour (across gaps)"], 1)


class StuckReadingTests(unittest.TestCase):
    def test_full_freeze_versus_one_steady_channel(self):
        start, step = datetime(2025, 4, 4, 19, 30), timedelta(minutes=30)
        rows = [(start + i * step, {"load": 137, "pv": 0, "battery": 129}) for i in range(6)]
        rows += [(start + (6 + i) * step, {"load": 1 + i, "pv": 0, "battery": -20}) for i in range(6)]
        stretches = stuck_runs(rows, ["load", "pv", "battery"], step=step, minimum_readings=6)
        self.assertEqual(len(stretches), 2)
        self.assertTrue(stretches[0]["all_channels_constant"])
        self.assertFalse(stretches[1]["all_channels_constant"])


class VillageComparisonTests(unittest.TestCase):
    def test_copied_month_found_and_night_zeros_ignored(self):
        hours = [datetime(2025, 2, 1) + timedelta(hours=h) for h in range(48)] + \
                [datetime(2025, 4, 1) + timedelta(hours=h) for h in range(48)]
        a = {t: (0.0 if t.hour < 6 else 100.0 + t.hour) for t in hours}
        b = {t: (a[t] if t.month == 2 else 0.0 if t.hour < 6 else 300.0 + t.hour) for t in hours}
        result = compare_village_sites({("household_1", "load"): a, ("household_2", "load"): b},
                                       ["household_1", "household_2"])
        copy = result["identical_nonzero_readings"][0]
        self.assertEqual(copy["identical_share_by_month"], {"2025-02": 1.0})   # April zeros match but don't count
        # 48 April values: 12 night zeros, then 306..323 twice each; middle two are 311 and 312
        self.assertEqual(result["monthly_median_load_w"]["household_2"]["2025-04"], 311.5)


class PowerBalanceTests(unittest.TestCase):
    def test_constant_loss_is_recovered(self):
        start = datetime(2025, 1, 1)
        rows = [(start + timedelta(minutes=30 * i),
                 {"load": load, "grid": load + 40 + 0.03 * load, "pv": 0.0, "battery": 0.0})
                for i, load in enumerate([50, 100, 200, 400, 800, 1600])]
        result = power_balance(rows)
        self.assertAlmostEqual(result["fitted_gap"]["fixed_w"], 40, places=6)
        self.assertAlmostEqual(result["fitted_gap"]["share_of_load"], 0.03, places=6)
        self.assertEqual(result["readings_over_100w_off_fit"], [])
        # gap = 40 W + 3%: over 20% of a 50, 100 or 200 W load (46 W = 23%), under 20% from 400 W up
        self.assertAlmostEqual(result["within_20pct_share"], 3 / 6)


if __name__ == "__main__":
    unittest.main()

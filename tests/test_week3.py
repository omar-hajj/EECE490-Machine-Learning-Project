"""Error analysis, worst-day explanations, backtest table, exact explanations and the final-test guard."""
import csv
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.evaluation import final_test
from lebanon_energy.evaluation.backtest_table import build
from lebanon_energy.evaluation.error_analysis import BASELINE, POINT, UPPER, analyse, explain
from lebanon_energy.models.explain import contributions, describe
from lebanon_energy.models.ridge import make_pipeline

START = datetime(2026, 6, 1)  # a Monday
POLICY = {"reserve_margin_fraction": 0.1, "minimum_run_hours": 3,
          "generators": [{"generator_id": "small", "usable_capacity_kw": 100.0},
                         {"generator_id": "large", "usable_capacity_kw": 300.0}],
          "allowed_configurations": [["small"], ["large"]]}


def predictions(days=35, miss_day=30, miss=80.0):
    """Flat 50 kW load forecast perfectly, except one day that runs `miss` kW higher."""
    rows = {}
    for hour in range(days * 24):
        stamp = START + timedelta(hours=hour)
        actual = 50.0 + (miss if hour // 24 == miss_day else 0.0)
        rows[stamp] = {"actual": actual, POINT: 50.0, UPPER: 60.0, BASELINE: 55.0}
    return rows


class ErrorAnalysisTests(unittest.TestCase):
    def test_groups_and_worst_day(self):
        holiday = (START + timedelta(days=9)).date()
        result = analyse(predictions(), {holiday})
        self.assertEqual(result["hours"], 35 * 24)
        self.assertEqual(result["groups"]["by_day_type"]["public holiday"]["hours"], 24)
        self.assertEqual(result["groups"]["by_day_type"]["day after a holiday"]["hours"], 24)
        self.assertEqual(len(result["groups"]["by_hour"]), 24)
        worst = result["worst_days"][0]
        self.assertEqual(worst["date"], (START + timedelta(days=30)).date().isoformat())
        self.assertAlmostEqual(worst["mae_kw"], 80.0)
        self.assertEqual(worst["hours_above_upper"], 24)
        self.assertAlmostEqual(worst["level_against_typical_weekday"], 1.6)
        self.assertIn("Under-forecast", worst["explanation"])
        self.assertIn("160% above a typical", worst["explanation"])
        self.assertAlmostEqual(result["overall"]["upper_coverage"], 1 - 24 / (35 * 24))

    def test_incomplete_days_are_not_ranked_and_empty_input_fails(self):
        rows = predictions()
        del rows[START + timedelta(days=30, hours=5)]
        self.assertNotEqual(analyse(rows, set())["worst_days"][0]["date"], (START + timedelta(days=30)).date().isoformat())
        with self.assertRaises(ValueError):
            analyse({START: {"actual": None, POINT: 1.0, UPPER: 1.0, BASELINE: 1.0}}, set())

    def test_explanation_names_holiday_context(self):
        facts = {"mean_forecast_kw": 100.0, "mean_actual_kw": 50.0, "actual_peak_kw": 60.0, "forecast_peak_kw": 120.0,
                 "worst_hour": "08:00", "worst_hour_error_kw": 70.0, "weekday": "Tuesday", "is_public_holiday": False,
                 "day_before_is_holiday": False, "week_before_is_holiday": True, "level_against_typical_weekday": -0.05}
        text = explain(facts)
        self.assertTrue(text.startswith("Over-forecast"))
        self.assertIn("same day last week was a holiday", text)
        self.assertNotIn("typical", text)


class BacktestTableTests(unittest.TestCase):
    def test_picks_needs_and_verdicts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "predictions.csv"
            with path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["timestamp_local", "actual", POINT, UPPER, BASELINE])
                writer.writeheader()
                for hour, (actual, upper) in enumerate([(50, 60), (150, 60), (50, 200), (50, ""), ("", 60)]):
                    writer.writerow({"timestamp_local": (START + timedelta(hours=hour)).isoformat(), "actual": actual,
                                     POINT: 50, UPPER: upper, BASELINE: 50})
            rows = build(path, POLICY)
        self.assertEqual([row["verdict"] for row in rows], ["right-sized", "undersized", "oversized", "", ""])
        self.assertEqual([row["picked"] for row in rows], ["small", "small", "large", "", "small"])
        self.assertEqual(rows[1]["needed"], "large")


class ExplainTests(unittest.TestCase):
    def test_contributions_add_up_exactly(self):
        rows = [{"hour_of_week": str(hour % 168), "lag_24h": 50.0 + hour % 24, "lag_168h": 40.0 + (hour * 7) % 31,
                 "lag_24h_is_holiday": float(hour % 50 == 0)} for hour in range(400)]
        targets = [0.5 * row["lag_24h"] + 0.3 * row["lag_168h"] + (10 if int(row["hour_of_week"]) % 24 == 8 else 0)
                   for row in rows]
        model = make_pipeline(1.0).fit(rows, targets)
        for row in rows[:5]:
            level, parts = contributions(model, row)
            self.assertAlmostEqual(level + math.fsum(parts.values()), float(model.predict([row])[0]), places=8)
        self.assertEqual(set(parts), {"hour_of_week", "lag_24h", "lag_168h", "lag_24h_is_holiday"})

    def test_descriptions(self):
        features = {"lag_24h": 120.0, "lag_168h": 90.0, "lag_24h_is_holiday": 0.0}
        parts = {"lag_24h": 30.0, "lag_168h": -8.0, "hour_of_week": 12.0, "lag_24h_is_holiday": -5.0}
        drivers = describe(features, parts, datetime(2026, 8, 11, 8), limit=3)
        self.assertEqual([d["input"] for d in drivers], ["lag_24h", "hour_of_week", "lag_168h"])  # flag is off: skipped
        self.assertIn("yesterday the load was 120 kW", drivers[0]["text"])
        self.assertIn("Tuesday at 08:00 is usually busier", drivers[1]["text"])
        holiday = describe(features, parts, datetime(2026, 8, 11, 8), holiday=True)
        self.assertIn("most recent Sunday", holiday[0]["text"])
        self.assertIn("treated as a Sunday", holiday[1]["text"])


class FinalTestGuardTests(unittest.TestCase):
    def test_refuses_when_the_test_was_already_opened(self):
        with tempfile.TemporaryDirectory() as folder:
            record = Path(folder) / "final_test_azm.json"
            record.write_text("{}", encoding="utf-8")
            with patch.object(final_test, "RECORD", record), \
                    patch.object(sys, "argv", ["final_test.py", "--archive", "missing.zip", "--open-test-set"]), \
                    patch.object(final_test, "read_net_load", side_effect=AssertionError("must not read data")):
                with self.assertRaises(SystemExit) as raised:
                    final_test.main()
            self.assertIn("already opened", str(raised.exception))

    def test_scores_only_the_requested_month_after_a_warm_up(self):
        calls = {}

        def fake_run(net, holidays, configuration, first_day, end_day, progress=None, weather=None):
            calls["first_day"], calls["end_day"] = first_day, end_day
            return {}

        with patch.object(final_test, "run", side_effect=fake_run), \
                patch.object(final_test, "summarize", return_value={"periods": {}}) as summarize:
            final_test.evaluate({}, datetime(2026, 9, 1), datetime(2026, 10, 1), {"quantile": 0.9}, None, set())
        self.assertEqual(calls["first_day"], datetime(2026, 8, 4))
        self.assertEqual(calls["end_day"], datetime(2026, 10, 1))
        self.assertEqual(summarize.call_args.args[3], {"September 2026": (datetime(2026, 9, 1), datetime(2026, 10, 1))})

    def test_default_run_is_a_rehearsal(self):
        self.assertFalse(final_test.RECORD.exists(), "The final test must not have been run yet")


if __name__ == "__main__":
    unittest.main()

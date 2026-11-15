"""Holiday-aware features, recent-error margin, hold rule, leakage check and serving bundle."""
from datetime import date, datetime, timedelta
import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lebanon_energy.api.service import forecast
from lebanon_energy.evaluation import run_log
from lebanon_energy.evaluation.leakage import check
from lebanon_energy.evaluation.missing_inputs import build_request
from lebanon_energy.features.history import history_calendar_features
from lebanon_energy.features.holidays import holiday_aware_features
from lebanon_energy.generators.policy import Generator, hold_short_dips, pick_errors
from lebanon_energy.models.walk_forward import ChangeFromLastWeek, recent_error_margin, upper_rank_value

START = datetime(2026, 6, 1)  # a Monday


def hourly(days, value=lambda stamp: float(stamp.hour + 10 * stamp.weekday())):
    return {START + timedelta(hours=h): value(START + timedelta(hours=h)) for h in range(days * 24)}


class HolidayFeatureTests(unittest.TestCase):
    def setUp(self):
        self.series = hourly(28)

    def test_matches_plain_features_without_holidays(self):
        stamp = datetime(2026, 6, 17, 9)
        plain, plain_time = history_calendar_features(self.series, stamp)
        aware, aware_time = holiday_aware_features(self.series, stamp, set())
        self.assertEqual({key: aware[key] for key in plain}, plain)
        self.assertEqual(aware["lag_24h_is_holiday"], 0.0)
        self.assertEqual(aware_time, plain_time)

    def test_holiday_is_forecast_from_recent_sundays(self):
        stamp = datetime(2026, 6, 17, 9)  # Wednesday
        features, available = holiday_aware_features(self.series, stamp, {date(2026, 6, 17)})
        self.assertEqual(features["hour_of_week"], str(6 * 24 + 9))
        self.assertEqual(features["lag_24h"], self.series[datetime(2026, 6, 14, 9)])
        self.assertEqual(features["lag_168h"], self.series[datetime(2026, 6, 7, 9)])
        self.assertLessEqual(available, stamp.replace(hour=0))

    def test_weekly_lag_skips_a_holiday(self):
        stamp = datetime(2026, 6, 24, 9)
        features, _ = holiday_aware_features(self.series, stamp, {date(2026, 6, 17)})
        self.assertEqual(features["lag_168h"], self.series[datetime(2026, 6, 10, 9)])
        self.assertEqual(features["lag_24h_is_holiday"], 0.0)
        after, _ = holiday_aware_features(self.series, datetime(2026, 6, 18, 9), {date(2026, 6, 17)})
        self.assertEqual(after["lag_24h_is_holiday"], 1.0)

    def test_missing_history_gives_no_features(self):
        del self.series[datetime(2026, 6, 16, 9)]
        self.assertEqual(holiday_aware_features(self.series, datetime(2026, 6, 17, 9), set()), (None, None))


class MarginTests(unittest.TestCase):
    def test_upper_rank_value(self):
        self.assertEqual(upper_rank_value(range(19), 0.9), 17.0)
        self.assertEqual(upper_rank_value([1, 2, 3], 0.9), 3.0)  # rank beyond n: largest value
        for values in ([], [float("nan")]):
            with self.assertRaises(ValueError):
                upper_rank_value(values, 0.9)

    def test_margin_uses_only_days_before_the_issue_time(self):
        issue = datetime(2026, 7, 1)
        residuals = {issue - timedelta(days=back) + timedelta(hours=8): float(back) for back in range(1, 11)}
        residuals[issue + timedelta(hours=8)] = 999.0  # the day being forecast must never count
        margin = recent_error_margin(residuals, issue, 8, quantile=0.9, window_days=28, minimum_days=7)
        self.assertEqual(margin, 10.0)
        self.assertEqual(recent_error_margin(residuals, issue, 8, quantile=0.9, window_days=5, minimum_days=5), 5.0)
        self.assertIsNone(recent_error_margin(residuals, issue, 9, quantile=0.9, window_days=28, minimum_days=7))
        self.assertIsNone(recent_error_margin(residuals, issue, 8, quantile=0.9, window_days=5, minimum_days=7))

    def test_change_from_last_week_adds_last_week_back(self):
        class Mean:
            def fit(self, rows, targets):
                self.value = math.fsum(targets) / len(targets)
                return self

            def predict(self, rows):
                return [self.value for _ in rows]

        model = ChangeFromLastWeek(Mean()).fit([{"lag_168h": 10.0}, {"lag_168h": 20.0}], [15.0, 25.0])
        self.assertEqual(model.predict([{"lag_168h": 400.0}]), [405.0])  # above anything seen in training


class HoldRuleTests(unittest.TestCase):
    def test_short_dip_between_larger_units_is_raised(self):
        self.assertEqual(hold_short_dips([300, 100, 100, 300, 100, 100, 100, 300], 3),
                         [300, 300, 300, 300, 100, 100, 100, 300])
        self.assertEqual(hold_short_dips([400, 100, 300], 3), [400, 300, 300])

    def test_capacity_is_never_lowered_and_edges_are_left_alone(self):
        original = [100, 300, 100, None, 100, 300]
        held = hold_short_dips(original, 3)
        self.assertEqual(held, [100, 300, 100, None, 100, 300])
        self.assertEqual(hold_short_dips([100, 300], 1), [100, 300])

    def test_pick_errors(self):
        units = [Generator("small", 100), Generator("large", 300)]
        result = pick_errors([50, 150, 50, 50], [100, 100, 300, None], units, allowed_configurations=[["small"], ["large"]])
        self.assertEqual((result["right_sized_hours"], result["undersized_hours"], result["oversized_hours"],
                          result["infeasible_forecast_hours"]), (1, 1, 1, 1))
        self.assertEqual(result["shortfall_kwh"], 50.0)


class LeakageAndServingTests(unittest.TestCase):
    def test_leakage_check_passes_and_counts_rows(self):
        series = hourly(21)
        rows, report = check(series, {date(2026, 6, 17)}, START + timedelta(days=8), START + timedelta(days=21))
        self.assertTrue(report["passed"])
        self.assertEqual(report["days_checked"], 13)
        self.assertEqual(len(rows), 13 * 24)
        self.assertTrue(all(row["latest_input_available_at_local"] <= row["issue_time_local"] for row in rows))

    def test_bundle_serves_a_full_day_and_degrades_without_history(self):
        from lebanon_energy.models.serving import build

        load = hourly(70, lambda stamp: 100.0 + 5 * stamp.hour + (30 if stamp.weekday() < 5 else 0))
        pv = hourly(70, lambda stamp: 20.0 if 9 <= stamp.hour <= 15 else 0.0)
        end = START + timedelta(days=63)
        configuration = {"ridge_alpha": 1.0, "quantile": 0.9, "recent_error_window_days": 14,
                         "recent_error_minimum_days": 7, "fallback_error_window_days": 28}
        policy = {"status": "test", "reserve_margin_fraction": 0.1, "minimum_run_hours": 1, "selection_rule": "test",
                  "generators": [{"generator_id": "small", "usable_capacity_kw": 200.0},
                                 {"generator_id": "large", "usable_capacity_kw": 400.0}],
                  "allowed_configurations": [["small"], ["large"]]}
        bundle = build({"load": load, "pv": pv}, set(), end, configuration, policy, "test")
        self.assertEqual(set(bundle["stored_margins_kw"]), {"ridge", "last_week", "weekday_average"})
        self.assertTrue(all(stamp < end for stamp in bundle["stored_ridge_errors_kw"]))
        issue = end + timedelta(days=3)
        full = forecast(bundle, build_request(load, pv, issue, 0))
        self.assertEqual(full["input_status"]["level"], "full")
        truth = load[issue + timedelta(hours=12)] - pv[issue + timedelta(hours=12)]
        self.assertAlmostEqual(full["hourly"][12]["net_kw"], truth, delta=5.0)
        self.assertGreaterEqual(full["hourly"][12]["net_upper_kw"], full["hourly"][12]["net_kw"] - 1e-6)
        why = full["peak_drivers"]
        self.assertTrue(why["available"])
        self.assertLessEqual(len(why["drivers"]), 3)
        from lebanon_energy.features.holidays import holiday_aware_features as build_features
        from lebanon_energy.models.explain import contributions
        net = {stamp: load[stamp] - pv[stamp] for stamp in load}
        stamp = issue + timedelta(hours=12)
        level, parts = contributions(bundle["models"]["net"], build_features(net, stamp, set())[0])
        self.assertAlmostEqual(level + math.fsum(parts.values()), full["hourly"][12]["net_kw"], places=6)
        late = forecast(bundle, build_request(load, pv, issue, 6))
        self.assertEqual(late["input_status"]["net_hours_by_method"], {"ridge": 18, "last_week": 6})
        empty = forecast(bundle, build_request(load, pv, issue, None))
        self.assertEqual(empty["input_status"]["net_hours_by_method"], {"weekday_average": 24})
        self.assertFalse(empty["peak_drivers"]["available"])
        self.assertTrue(all(row["generator"]["capacity_kw"] is not None for row in empty["hourly"]))
        nothing = forecast(bundle, build_request(load, pv, issue, None, apply_fallbacks=False))
        self.assertEqual(nothing["input_status"]["level"], "unavailable")

    def test_run_log_appends_with_one_header(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "log.csv"
            row = dict.fromkeys(run_log.COLUMNS, "x")
            run_log.append([row], path)
            run_log.append([row, row], path)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 4)
            with self.assertRaises(ValueError):
                run_log.append([{**row, "unknown": 1}], path)


if __name__ == "__main__":
    unittest.main()

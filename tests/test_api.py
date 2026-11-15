"""Forecast request safety, fallbacks, upper estimate and generator advice."""
from datetime import date, datetime, timedelta
import unittest
from fastapi.testclient import TestClient
from lebanon_energy.api.service import create_app
from lebanon_energy.models.azm_backtest import residual_correction


class ConstantModel:
    def __init__(self, value):
        self.value = value

    def predict(self, rows):
        return [self.value for _ in rows]


POLICY = {'status': 'test_policy', 'reserve_margin_fraction': 0.1, 'minimum_run_hours': 1,
          'selection_rule': 'Smallest configuration that covers the upper estimate.',
          'generators': [{'generator_id': 'small', 'usable_capacity_kw': 100.0},
                         {'generator_id': 'large', 'usable_capacity_kw': 300.0}],
          'allowed_configurations': [['small'], ['large']]}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.issue = datetime(2026, 8, 10)
        cutoff = datetime(2026, 8, 1)
        profile = lambda value: {(day, hour): (value, cutoff) for day in range(7) for hour in range(24)}
        self.bundle = {'models': {'net': ConstantModel(80.0), 'load': ConstantModel(100.0)},
                       'training_end_exclusive': cutoff,
                       'profiles': {'load': profile(20.0), 'pv': profile(5.0), 'net': profile(15.0)},
                       'stored_margins_kw': {method: {hour: 10.0 for hour in range(24)}
                                             for method in ('ridge', 'last_week', 'weekday_average')},
                       'stored_ridge_errors_kw': {}, 'quantile': 0.9, 'recent_error_window_days': 28,
                       'recent_error_minimum_days': 7, 'holidays': [date(2026, 8, 15)],
                       'holiday_covered_periods': [(date(2026, 4, 16), date(2026, 9, 30))],
                       'generator_policy': POLICY, 'source_sha256': 'test'}
        self.client = TestClient(create_app(self.bundle))

    def request(self, readings=None, issue=None, **extra):
        return self.client.post('/forecast', json={'issue_time_local': (issue or self.issue).isoformat(),
                                                   'readings': readings or [], **extra})

    def reading(self, lag, hour=0, load=70.0, pv=10.0):
        return {'timestamp_local': (self.issue + timedelta(hours=hour - lag)).isoformat(), 'load_kw': load, 'pv_kw': pv}

    def test_main_model_then_last_week_then_profile(self):
        response = self.request([self.reading(24), self.reading(168), self.reading(168, 1)])
        self.assertEqual(response.status_code, 200)
        data = response.json()
        rows = data['hourly']
        self.assertEqual(len(rows), 24)
        self.assertEqual([row['net_method'] for row in rows[:3]], ['ridge', 'last_week', 'weekday_average'])
        self.assertEqual([row['net_kw'] for row in rows[:3]], [80.0, 60.0, 15.0])
        self.assertEqual(rows[0]['load_kw'], 100.0)
        self.assertIsNone(rows[0]['net_fallback_reason'])
        self.assertEqual(rows[1]['net_fallback_reason'], 'recent_meter_history_missing')
        self.assertEqual(data['input_status']['level'], 'fallback')
        self.assertFalse(data['input_status']['weather_required'])

    def test_upper_estimate_drives_the_generator_pick(self):
        rows = self.request([self.reading(24), self.reading(168)]).json()['hourly']
        # 80 kW forecast + 10 kW stored margin = 90; with 10% reserve that needs 99 kW: the small unit.
        self.assertEqual(rows[0]['net_upper_kw'], 90.0)
        self.assertEqual(rows[0]['margin_basis'], 'stored_errors')
        self.assertEqual(rows[0]['generator']['configurations'], [['small']])
        self.bundle['stored_margins_kw']['ridge'][0] = 20.0  # 100 kW upper needs 110 kW: the large unit
        rows = self.request([self.reading(24), self.reading(168)]).json()['hourly']
        self.assertEqual(rows[0]['generator']['configurations'], [['large']])
        self.assertEqual(rows[0]['generator']['capacity_kw'], 300.0)

    def test_recent_errors_replace_the_stored_margin(self):
        # Net load of 95 kW at 00:00 on every earlier day: the constant 80 kW model is 15 kW low each time.
        readings = [self.reading(24 * days, load=105.0, pv=10.0) for days in range(1, 40)]
        row = self.request(readings).json()['hourly'][0]
        self.assertEqual(row['net_method'], 'ridge')
        self.assertEqual(row['margin_basis'], 'recent_errors')
        self.assertAlmostEqual(row['margin_kw'], 15.0)
        self.assertAlmostEqual(row['net_upper_kw'], 95.0)

    def test_full_inputs_and_fallbacks_switched_off(self):
        readings = [self.reading(lag, hour) for hour in range(24) for lag in (24, 168)]
        data = self.request(readings).json()
        self.assertEqual(data['input_status']['level'], 'full')
        data = self.request([], apply_fallbacks=False).json()
        self.assertEqual(data['input_status']['level'], 'unavailable')
        self.assertTrue(all(row['net_upper_kw'] is None and row['generator']['status'] == 'unavailable'
                            for row in data['hourly']))

    def test_demand_above_every_configuration_is_reported(self):
        self.bundle['models']['net'] = ConstantModel(500.0)
        row = self.request([self.reading(24), self.reading(168)]).json()['hourly'][0]
        self.assertEqual(row['generator']['status'], 'insufficient_available_capacity')
        self.assertEqual(row['generator']['configurations'], [])

    def test_short_dip_is_held_on_the_larger_unit(self):
        self.bundle['generator_policy'] = {**POLICY, 'minimum_run_hours': 3}
        for hour in range(24):
            self.bundle['stored_margins_kw']['weekday_average'][hour] = 200.0 if hour != 5 else 10.0
        rows = self.request().json()['hourly']
        self.assertTrue(rows[5]['generator']['held_through_short_dip'])
        self.assertEqual(rows[5]['generator']['configurations'], [['large']])
        self.assertFalse(rows[4]['generator']['held_through_short_dip'])

    def test_holiday_calendar_gap_is_flagged(self):
        self.bundle['holiday_covered_periods'] = [(date(2026, 4, 16), date(2026, 8, 1))]
        self.assertFalse(self.request().json()['input_status']['holiday_calendar_known'])

    def test_invalid_or_future_data_and_extra_fields_rejected(self):
        valid = self.reading(24)
        for readings in ([valid, valid], [{'timestamp_local': self.issue.isoformat(), 'load_kw': 1}],
                         [{**valid, 'load_kw': -1}], [{**valid, 'load_kw': 'NaN'}],
                         [{**valid, 'timestamp_local': '2026-08-09T00:30:00'}],
                         [{**valid, 'timestamp_local': '2026-08-09T00:00:00+03:00'}],
                         [{**valid, 'unexpected': 1}]):
            with self.subTest(readings=readings):
                self.assertEqual(self.request(readings).status_code, 422)

    def test_training_cutoff_midnight_and_dst_rejected(self):
        for issue in (datetime(2026, 7, 31), datetime(2026, 8, 10, 1), datetime(2026, 10, 24)):
            with self.subTest(issue=issue):
                self.assertEqual(self.request(issue=issue).status_code, 422)

    def test_no_profile_no_history_reports_unavailable(self):
        self.bundle['profiles'] = {'load': {}, 'pv': {}, 'net': {}}
        data = self.request().json()
        row = data['hourly'][0]
        self.assertIsNone(row['load_kw'])
        self.assertIsNone(row['net_kw'])
        self.assertEqual(row['net_method'], 'unavailable')
        self.assertEqual(data['input_status']['level'], 'unavailable')

    def test_missing_bundle_returns_service_unavailable(self):
        from unittest.mock import patch
        with patch.dict('os.environ', {'AZM_MODEL_PATH': 'outputs/nonexistent-model.joblib'}):
            client = TestClient(create_app())
            self.assertEqual(client.get('/health').json()['status'], 'model_missing')
            self.assertEqual(client.post('/forecast', json={'issue_time_local': self.issue.isoformat()}).status_code, 503)

    def test_calibration_rank_and_invalid_samples(self):
        self.assertEqual(residual_correction(range(19)), 17.)
        for values in ([], [1], [float('nan')] * 20):
            with self.assertRaises(ValueError):
                residual_correction(values)


if __name__ == '__main__':
    unittest.main()

"""Forecast request safety and explicit fallback behavior."""
from datetime import datetime, timedelta
import unittest
from fastapi.testclient import TestClient
from lebanon_energy.api import create_app
from lebanon_energy.azm_backtest import residual_correction


class ConstantModel:
    def predict(self, rows):
        return [100.0 for _ in rows]


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.issue = datetime(2026, 8, 10)
        available = datetime(2026, 8, 1)
        profile = {(day, hour): (20., available) for day in range(7) for hour in range(24)}
        self.bundle = {'model': ConstantModel(), 'training_end_exclusive': available,
                       'profiles': {'load': profile, 'pv': profile},
                       'selection_period': 'June 2026', 'source_sha256': 'test'}
        self.client = TestClient(create_app(self.bundle))

    def request(self, readings=None, issue=None):
        return self.client.post('/forecast', json={'issue_time_local': (issue or self.issue).isoformat(),
                                                   'readings': readings or []})

    def reading(self, lag, hour=0):
        return {'timestamp_local': (self.issue + timedelta(hours=hour-lag)).isoformat(), 'load_kw': 70.}

    def test_ridge_then_weekly_then_profile_and_signed_net(self):
        response = self.request([self.reading(24), self.reading(168), self.reading(168, 1)])
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['hourly']), 24)
        self.assertEqual([r['load_method'] for r in data['hourly'][:3]],
                         ['ridge', 'last_week', 'weekday_average'])
        self.assertEqual(data['hourly'][0]['signed_net_kw'], 80.)
        self.assertFalse(data['generator_advice']['available'])

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
        self.bundle['profiles'] = {'load': {}, 'pv': {}}
        row = self.request().json()['hourly'][0]
        self.assertIsNone(row['load_kw'])
        self.assertIsNone(row['signed_net_kw'])
        self.assertEqual(row['load_method'], 'unavailable')

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

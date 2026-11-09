"""Unseen-site isolation, fixed unit conversion and time-window tests."""
from datetime import datetime, timedelta
import io
import unittest
from unittest.mock import MagicMock

from lebanon_energy.location_trial import feature_row, tune_refit
from lebanon_energy.village import check_holdout, load_series_kw
from lebanon_energy.weather import VARIABLES


def entry(timestamp):
    return {'features': {name: 10. for name in VARIABLES},
            'nominal_available_at_local': timestamp - timedelta(days=1)}


class LocationTrialTests(unittest.TestCase):
    def test_location_features_are_invariant_to_target_history(self):
        stamp = datetime(2025, 6, 1, 10)
        weather = {stamp: entry(stamp)}
        before = feature_row({stamp: 1.}, weather, stamp, 'location_only', 33.2993, 35.31123)
        after = feature_row({stamp: 999999., stamp-timedelta(days=1): 88888.}, weather, stamp, 'location_only', 33.2993, 35.31123)
        self.assertEqual(before, after)
        self.assertFalse(any('lag' in key or 'site' in key or 'scale' in key for key in before[0]))

    def test_known_related_sites_must_be_excluded_together(self):
        with self.assertRaises(ValueError):
            check_holdout(['household_2'], ['household_1'])
        check_holdout(['industrial_1'], ['household_1', 'household_2'])
        with self.assertRaises(ValueError):
            check_holdout(['household_3'], ['household_3'])

    def test_confirmed_watts_are_converted_with_no_target_based_scaling(self):
        path = MagicMock()
        path.open.return_value = io.StringIO('site_id,target,timestamp_local_unverified,value_source_units\nhousehold_3,load,2025-06-01T00:00:00,1500\n')
        sites = {'sites':[{'site_id':'household_3','power_unit_confirmed':'W','meter_clock':'Asia/Beirut','meter_clock_observes_dst':True}]}
        result = load_series_kw(path, sites, ['household_3'], datetime(2025,7,1))
        self.assertEqual(result[('household_3','load')][datetime(2025,6,1)],1.5)

    def test_clock_conflicts_are_blocked(self):
        sites = {'sites':[{'site_id':'municipality','clock_verification_status':'conflict_pending'}]}
        with self.assertRaisesRegex(ValueError,'clock conflict'):
            load_series_kw(MagicMock(),sites,['municipality'],datetime(2025,7,1))

    def test_june_actuals_cannot_change_may_selection_or_refit(self):
        dates = [datetime(2025, month, 1, hour) for month in (4,5,6) for hour in (0,1)]
        values = {stamp: float(index+1) for index,stamp in enumerate(dates)}
        series = {('household_3','load'):values}
        weather = {stamp:entry(stamp) for stamp in dates}
        config = {'training_start':'2025-04-01','inner_validation_start':'2025-05-01','evaluation_start':'2025-06-01',
                  'ridge_alphas':[1.], 'xgboost_candidates':[]}
        before, info_before = tune_refit(['household_3'],'load',series,weather,config,'location_only',(33.2993,35.31123))
        values[datetime(2025,6,1)] = 999999.
        after, info_after = tune_refit(['household_3'],'load',series,weather,config,'location_only',(33.2993,35.31123))
        self.assertEqual(info_before,info_after)
        x = [feature_row({},weather,datetime(2025,6,1),'location_only',33.2993,35.31123)[0]]
        self.assertAlmostEqual(float(before.predict(x)[0]),float(after.predict(x)[0]))


if __name__ == '__main__':
    unittest.main()

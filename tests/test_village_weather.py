"""Check weather request scope, UTC storage and cache reuse without network."""
import contextlib
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.download_village_weather import VARIABLES, main


class VillageWeatherTests(unittest.TestCase):
    def test_only_prepared_months_are_requested_and_cached_utc_is_reused(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / 'baseline'
            baseline.mkdir()
            sites = root / 'sites.json'
            sites.write_text(json.dumps({'sites':[{'site_id':'household_1','location_group':'deir_qanoun_en_nahr'}],
                'location_groups':{'deir_qanoun_en_nahr':{'representative_latitude':33.2993,'representative_longitude':35.31123,
                    'village_point_weather_use_approved_by_user':'2026-11-09'}}}))
            (baseline / 'results.json').write_text(json.dumps({'groups':[{'site_id':'household_1','validation_end_exclusive':'2025-07-01'}]}))
            (baseline / 'hourly_data.csv').write_text('site_id,timestamp_local_unverified\nhousehold_1,2025-06-01T00:00:00\n')
            epochs = [int(datetime(2025,6,1,hour,tzinfo=timezone.utc).timestamp()) for hour in range(2)]
            payload = {'utc_offset_seconds':0,'latitude':33.3,'longitude':35.3,
                       'hourly':{'time':epochs,**{name+'_previous_day1':[1.,2.] for name in VARIABLES}},
                       'hourly_units':{name+'_previous_day1':'test_unit' for name in VARIABLES}}
            arguments = ['download_village_weather.py','--sites',str(sites),'--baseline-dir',str(baseline),
                         '--output-dir',str(root / 'weather')]
            with patch('sys.argv',arguments), patch('scripts.download_village_weather.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as request, patch('scripts.download_village_weather.time.sleep'), contextlib.redirect_stdout(io.StringIO()):
                main()
            url = request.call_args.args[0]
            self.assertIn('start_date=2025-05-31',url)
            self.assertIn('end_date=2025-06-30',url)
            self.assertIn('timezone=GMT',url)
            self.assertNotIn('2025-07',url)
            manifest = json.loads((root/'weather'/'manifest.json').read_text())
            self.assertEqual(manifest['unique_utc_weather_hours'],2)
            self.assertFalse(manifest['weather_join_applied'])
            self.assertFalse(manifest['publication_availability_verified'])
            with patch('sys.argv',arguments), patch('scripts.download_village_weather.urlopen') as request, contextlib.redirect_stdout(io.StringIO()):
                main()
                request.assert_not_called()


if __name__ == '__main__':
    unittest.main()

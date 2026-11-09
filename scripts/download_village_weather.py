"""Cache nominal day-ahead forecast weather for approved village coordinates.

Download UTC forecasts for months represented in the approved training and
validation inputs. No reserved test month, observed future weather, meter
clock assumption or automatic unit conversion is introduced.
"""

import argparse
import calendar
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import urlopen


VARIABLES = ["temperature_2m", "relative_humidity_2m", "cloud_cover",
             "shortwave_radiation", "diffuse_radiation", "direct_radiation"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sites', required=True, type=Path)
    parser.add_argument('--baseline-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.sites.read_text(encoding='utf-8'))
    group_id = 'deir_qanoun_en_nahr'
    group = data['location_groups'][group_id]
    if not group.get('village_point_weather_use_approved_by_user'):
        raise ValueError('Village-point weather use needs user approval')
    sites = {site['site_id'] for site in data['sites'] if site.get('location_group') == group_id}
    baseline = json.loads((args.baseline_dir / 'results.json').read_text())
    cutoffs = {item['site_id']: datetime.fromisoformat(item['validation_end_exclusive']) for item in baseline['groups']}
    months = set()
    with (args.baseline_dir / 'hourly_data.csv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['site_id'] in sites:
                stamp = datetime.fromisoformat(row['timestamp_local_unverified'])
                if stamp >= cutoffs[row['site_id']]:
                    raise ValueError('Reserved test target appears in prepared data')
                months.add((stamp.year, stamp.month))
    if not months:
        raise ValueError('No prepared village observations found')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    all_rows, requests = {}, []
    variables = [name + '_previous_day1' for name in VARIABLES]
    for year, month in sorted(months):
        first = datetime(year, month, 1)
        # Padding before each represented month accommodates positive local
        # offsets after the meter clock is confirmed; the response stays UTC.
        start = first - timedelta(days=1)
        end = datetime(year, month, calendar.monthrange(year, month)[1])
        parameters = {'latitude':group['representative_latitude'], 'longitude':group['representative_longitude'],
                      'start_date':start.strftime('%Y-%m-%d'), 'end_date':end.strftime('%Y-%m-%d'),
                      'hourly':','.join(variables), 'timezone':'GMT', 'timeformat':'unixtime'}
        url = 'https://previous-runs-api.open-meteo.com/v1/forecast?' + urlencode(parameters)
        path = args.output_dir / f'{year}-{month:02d}.json'
        if path.exists():
            envelope = json.loads(path.read_text())
            if envelope['request_url'] != url:
                raise ValueError('Cached request differs; use a different output directory')
        else:
            with urlopen(url, timeout=40) as response:
                payload = json.loads(response.read())
            if payload.get('error'):
                raise ValueError(payload.get('reason', 'Weather API error'))
            envelope = {'request_url':url, 'retrieved_at_utc':datetime.now(timezone.utc).isoformat(), 'response':payload}
            path.write_text(json.dumps(envelope,indent=2),encoding='utf-8')
            time.sleep(0.25)
        payload = envelope['response']
        hourly = payload['hourly']
        if payload.get('utc_offset_seconds') != 0:
            raise ValueError('Expected UTC weather timestamps')
        if any(len(hourly[name]) != len(hourly['time']) for name in variables):
            raise ValueError('Weather column lengths differ')
        missing = 0
        for index, epoch in enumerate(hourly['time']):
            stamp = datetime.fromtimestamp(epoch, timezone.utc)
            row = {'valid_time_utc':stamp.isoformat(),
                   'nominal_forecast_time_utc':(stamp-timedelta(hours=24)).isoformat(),
                   **{name:hourly[name][index] for name in variables}}
            missing += any(row[name] is None for name in variables)
            if stamp in all_rows and all_rows[stamp] != row:
                raise ValueError('Overlapping weather responses disagree; no response selected automatically')
            all_rows[stamp] = row
        requests.append({'month':f'{year}-{month:02d}', 'request_url':url,
                         'response_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                         'weather_grid_latitude':payload['latitude'], 'weather_grid_longitude':payload['longitude'],
                         'missing_value_hours':missing, 'units':payload['hourly_units']})
        print(f'Cached village forecast weather for {year}-{month:02d}; {missing} hours with missing values.',flush=True)
    rows = [all_rows[key] for key in sorted(all_rows)]
    with (args.output_dir / 'forecasts_utc.csv').open('w',encoding='utf-8',newline='') as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {'location_group':group_id,'site_ids':sorted(sites),'village_location':group,
                'requests':requests,'unique_utc_weather_hours':len(rows),
                'model_selection':'Provider default best_match; cached responses preserved, not a pinned single-run reconstruction',
                'meter_clock_conversion_applied':False,'weather_join_applied':False,
                'publication_availability_verified':False,'reserved_test_target_month_requested':False,
                'limitations':['Village representative coordinates, not building coordinates.',
                               'Nominal previous_day1 timing does not verify historical publication times.',
                               'Site clocks and units must be confirmed before joining or pooling observations.',
                               'UTC date padding may include the day before an available source month; no test labels used.'],
                'references':['https://open-meteo.com/en/docs/previous-runs-api','https://mapcarta.com/12896870']}
    (args.output_dir / 'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Saved {len(rows)} UTC forecast hours. No meter data joined or models retrained.')


if __name__ == '__main__':
    main()

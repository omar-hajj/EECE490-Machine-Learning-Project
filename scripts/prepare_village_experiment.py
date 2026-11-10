"""Prepare the user-approved April-June six-site experiment without edits to sources."""
import argparse
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from lebanon_energy.data.preparation import file_sha256
from lebanon_energy.features.village import load_series_kw, load_village_weather
from lebanon_energy.data.weather import VARIABLES, aligned_features


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-dir', required=True, type=Path)
    parser.add_argument('--weather-dir', required=True, type=Path)
    parser.add_argument('--sites', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config.get('approved_by_user') is not True:
        raise ValueError('Experiment protocol requires approval')
    sites = json.loads(args.sites.read_text(encoding='utf-8'))
    group = sites['location_groups']['deir_qanoun_en_nahr']
    reference = json.loads((args.baseline_dir / 'results.json').read_text())
    if file_sha256(args.archive) != reference['source_sha256']:
        raise ValueError('Source archive differs from prepared data')
    start, end = datetime.fromisoformat(config['training_start']), datetime.fromisoformat(config['evaluation_end_exclusive'])
    series = load_series_kw(args.baseline_dir / 'hourly_data.csv', sites, config['site_ids'], end)
    weather = load_village_weather(args.weather_dir / 'forecasts_utc.csv')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    weather_rows, stamp = [], start
    while stamp < end:
        entry = aligned_features(weather, stamp)
        if entry is None:
            raise ValueError(f'Missing forecast inputs at {stamp}; no fill applied')
        weather_rows.append({'timestamp_local': stamp.isoformat(), **entry['features'],
                             'nominal_available_at_local': entry['nominal_available_at_local'].isoformat(),
                             'nominal_available_at_utc': entry['nominal_available_at_utc'].isoformat()})
        stamp += timedelta(hours=1)
    with (args.output_dir / 'weather_features.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(weather_rows[0])); writer.writeheader(); writer.writerows(weather_rows)
    rows = []
    for (site_id, target), values in series.items():
        for timestamp, value in sorted(values.items()):
            rows.append({'site_id': site_id, 'target': target, 'timestamp_local': timestamp.isoformat(), 'value_kw': value})
    with (args.output_dir / 'history_kw.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    report = {'protocol': config, 'village': group, 'source_sha256': reference['source_sha256'],
              'input_sha256': {str(path): file_sha256(path) for path in (args.sites, args.config, args.baseline_dir / 'hourly_data.csv', args.weather_dir / 'forecasts_utc.csv')},
              'weather_feature_hours': len(weather_rows), 'normalized_history_rows': len(rows),
              'unit_conversion': {site: 'Confirmed W to kW by multiplying by 0.001' for site in config['site_ids']},
              'weather_publication_verified': False, 'data_corrected_or_imputed': False,
              'july_test_included': False, 'municipality_included': False,
              'limitations': ['One village, approximate shared coordinates, preliminary nominal forecast availability.',
                              'This is an unseen-site comparison within the village, not nationwide geographic validation.',
                              'History before April is retained only for historical lag lookups; model fitting/tuning uses approved April-May windows.']}
    (args.output_dir / 'metadata.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Prepared {len(weather_rows)} calendar weather hours and {len(rows)} confirmed-kW history rows. Municipality and July excluded.')


if __name__ == '__main__':
    main()

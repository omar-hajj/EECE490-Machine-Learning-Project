"""Approved six-site, nested time/site holdout comparison of input modes."""

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import csv
import importlib.metadata
import json
import math
from pathlib import Path

from ..data.preparation import source_path, file_sha256
from ..models.baselines import METHODS, fit_weekday_profile, predict
from ..models.boosting import make_pipeline as boosting_pipeline
from ..evaluation.metrics import compare_modes, score
from ..models.ridge import make_pipeline as ridge_pipeline
from ..features.village import check_holdout, history_features, location_features
from ..data.weather import VARIABLES


def read_prepared(directory, config):
    metadata = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
    if metadata['protocol'] != config or metadata['municipality_included'] or metadata['july_test_included']:
        raise ValueError('Prepared inputs do not match the approved experiment')
    series = {}
    end = datetime.fromisoformat(config['evaluation_end_exclusive'])
    with (directory / 'history_kw.csv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            site, target = row['site_id'], row['target']
            if site not in config['site_ids'] or target not in {'load', 'pv'}:
                raise ValueError('Unapproved site/target')
            timestamp = datetime.fromisoformat(row['timestamp_local'])
            value = float(row['value_kw'])
            if timestamp >= end or not math.isfinite(value) or value < 0:
                raise ValueError('Unexpected test target or invalid value')
            values = series.setdefault((site, target), {})
            if timestamp in values:
                raise ValueError('Duplicate target')
            values[timestamp] = value
    weather = {}
    with (directory / 'weather_features.csv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            timestamp = datetime.fromisoformat(row['timestamp_local'])
            if timestamp >= end or timestamp in weather:
                raise ValueError('Unexpected weather target hour')
            weather[timestamp] = {'features': {name: float(row[name]) for name in VARIABLES},
                                  'nominal_available_at_local': datetime.fromisoformat(row['nominal_available_at_local'])}
    return metadata, series, weather


def feature_row(series, weather, timestamp, mode, latitude, longitude):
    if mode == 'location_only':
        return location_features(timestamp, weather.get(timestamp), latitude, longitude)
    if mode == 'history':
        return history_features(series, timestamp, weather.get(timestamp), latitude, longitude)
    raise ValueError('Unknown input mode')


def rows_for(site_ids, target, series, weather, start, end, mode, coordinates):
    rows = []
    for site in site_ids:
        values = series[(site, target)]
        timestamp = start
        while timestamp < end:
            actual = values.get(timestamp)
            features, available = feature_row(values, weather, timestamp, mode, *coordinates)
            if features is not None and actual is not None:
                rows.append({'site_id': site, 'timestamp': timestamp, 'actual': actual,
                             'features': features, 'available_at': available})
            timestamp += timedelta(hours=1)
    return rows


def factory(candidate):
    if candidate['family'] == 'Ridge':
        return ridge_pipeline(**candidate['parameters'])
    if candidate['family'] == 'XGBoost':
        return boosting_pipeline(**candidate['parameters'])
    raise ValueError('Unknown model family')


def tune_refit(site_ids, target, series, weather, config, mode, coordinates):
    train_start, select_start, eval_start = (datetime.fromisoformat(config[name]) for name in
                                            ('training_start', 'inner_validation_start', 'evaluation_start'))
    inner_train = rows_for(site_ids, target, series, weather, train_start, select_start, mode, coordinates)
    inner_validation = rows_for(site_ids, target, series, weather, select_start, eval_start, mode, coordinates)
    refit = rows_for(site_ids, target, series, weather, train_start, eval_start, mode, coordinates)
    if not inner_train or not inner_validation:
        raise ValueError('No inner training or validation rows')
    candidates = ([{'family': 'Ridge', 'parameters': {'alpha': alpha}} for alpha in config['ridge_alphas']] +
                  [{'family': 'XGBoost', 'parameters': parameters} for parameters in config['xgboost_candidates']])
    log, best = [], None
    for candidate in candidates:
        model = factory(candidate)
        model.fit([row['features'] for row in inner_train], [row['actual'] for row in inner_train])
        predictions = model.predict([row['features'] for row in inner_validation]).tolist()
        scores = asdict(score([row['actual'] for row in inner_validation], predictions))
        item = {**candidate, 'may_scores': scores}
        log.append(item)
        if best is None or scores['mae'] < best['may_scores']['mae']:
            best = item
    model = factory(best)
    model.fit([row['features'] for row in refit], [row['actual'] for row in refit])
    information = {'mode': mode, 'training_site_ids': sorted(site_ids), 'selection_site_ids': sorted(site_ids),
                   'training_start': train_start.isoformat(), 'inner_validation_start': select_start.isoformat(),
                   'refit_end_exclusive': eval_start.isoformat(), 'inner_training_rows': len(inner_train),
                   'inner_validation_rows': len(inner_validation), 'refit_rows': len(refit),
                   'selected_candidate': best, 'candidate_log': log,
                   'feature_keys': sorted(refit[0]['features']),
                   'last_refit_target': max(row['timestamp'] for row in refit).isoformat()}
    return model, information


def baseline_profile(series, start, end):
    return fit_weekday_profile({stamp: value for stamp, value in series.items() if start <= stamp < end}, end)


def select_history_baseline(series, config):
    start, select_start, end = (datetime.fromisoformat(config[name]) for name in
                               ('training_start', 'inner_validation_start', 'evaluation_start'))
    profile = baseline_profile(series, start, select_start)
    paired = []
    stamp = select_start
    while stamp < end:
        results = {method: predict(series, profile, stamp, method) for method in METHODS}
        if stamp in series and all(value is not None for value in results.values()):
            paired.append((series[stamp], results))
        stamp += timedelta(hours=1)
    if not paired:
        raise ValueError('No common May baseline hours')
    scores = {method: asdict(score([actual for actual, _ in paired], [row[method][0] for _, row in paired])) for method in METHODS}
    best = min(METHODS, key=lambda method: scores[method]['mae'])
    return best, scores, baseline_profile(series, start, end)


def main():
    import joblib
    from threadpoolctl import threadpool_limits
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-dir', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config.get('approved_by_user') is not True:
        raise ValueError('Protocol needs approval')
    flat = [site for group in config['holdout_groups'] for site in group]
    if set(flat) != set(config['site_ids']) or len(flat) != len(set(flat)):
        raise ValueError('Each approved site must be held out exactly once')
    metadata, series, weather = read_prepared(args.prepared_dir, config)
    if file_sha256(args.archive) != metadata['source_sha256']:
        raise ValueError('Original source differs')
    coordinates = metadata['village']['representative_latitude'], metadata['village']['representative_longitude']
    start, end = (datetime.fromisoformat(config[name]) for name in ('evaluation_start', 'evaluation_end_exclusive'))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'models').mkdir(exist_ok=True)
    report = {'protocol': config, 'source_sha256': metadata['source_sha256'], 'run_time_utc': datetime.now(timezone.utc).isoformat(),
              'input_sha256': {name: file_sha256(args.prepared_dir / name) for name in ('metadata.json', 'history_kw.csv', 'weather_features.csv')},
              'code_sha256': {path.name: file_sha256(path) for path in (Path(__file__), source_path("features.village"), source_path("features.history"))},
              'versions': {name: importlib.metadata.version(name) for name in ('scikit-learn', 'xgboost', 'numpy', 'tzdata')},
              'location_models': [], 'groups': [], 'final_test_scored': False, 'municipality_included': False,
              'acceptance_status': 'awaiting_user_limits_after_measured_comparison', 'deployment_model_selected': False,
              'limitations': ['Within-village unseen-site development comparison; not nationwide or unseen-location validation.',
                              'All six sites have the same representative location and weather, so those inputs cannot identify building size or equipment.',
                              'Nominal forecast timing is preliminary; actual publication times remain unverified.',
                              'June is outer evaluation only; July remains reserved. History comparisons can use earlier observed June readings available at each issue time.',
                              'No target-site demand/PV history or site-specific scale is used to train, tune or predict location-only mode.',
                              'Raw predictions are primary; nonnegative clipping is a separate diagnostic.']}
    all_predictions = []
    with threadpool_limits(limits=1):
        for heldout in config['holdout_groups']:
            training_sites = [site for site in config['site_ids'] if site not in heldout]
            check_holdout(training_sites, heldout)
            fold = '_'.join(heldout)
            for target in ('load', 'pv'):
                location_model, location_info = tune_refit(training_sites, target, series, weather, config, 'location_only', coordinates)
                location_path = args.output_dir / 'models' / f'{fold}_{target}_location.joblib'
                joblib.dump(location_model, location_path)
                location_info.update({'heldout_site_ids': heldout, 'target': target, 'model_file': str(location_path.relative_to(args.output_dir)),
                                      'model_sha256': file_sha256(location_path)})
                report['location_models'].append(location_info)
                print(f'Location-only {target}: held out {", ".join(heldout)}; tuning used other sites in May.', flush=True)
                for site in heldout:
                    values = series[(site, target)]
                    history_model, history_info = tune_refit([site], target, series, weather, config, 'history', coordinates)
                    baseline_method, baseline_scores, profile = select_history_baseline(values, config)
                    use_baseline = baseline_scores[baseline_method]['mae'] <= history_info['selected_candidate']['may_scores']['mae']
                    history_path = args.output_dir / 'models' / f'{site}_{target}_history_ml.joblib'
                    joblib.dump(history_model, history_path)
                    history_info.update({'model_file': str(history_path.relative_to(args.output_dir)), 'model_sha256': file_sha256(history_path),
                                         'selected_history_kind': 'baseline' if use_baseline else 'ml',
                                         'selected_baseline_method': baseline_method, 'may_baseline_scores': baseline_scores})
                    june_rows, stamp = [], start
                    while stamp < end:
                        loc, loc_available = location_features(stamp, weather.get(stamp), *coordinates)
                        hist, hist_available = history_features(values, stamp, weather.get(stamp), *coordinates)
                        june_rows.append({'timestamp': stamp, 'actual': values.get(stamp), 'location_features': loc,
                                          'history_features': hist, 'location_available': loc_available, 'history_available': hist_available})
                        stamp += timedelta(hours=1)
                    loc_rows = [row for row in june_rows if row['location_features'] is not None]
                    loc_predictions = iter(location_model.predict([row['location_features'] for row in loc_rows]).tolist())
                    hist_rows = [row for row in june_rows if row['history_features'] is not None]
                    hist_predictions = iter(history_model.predict([row['history_features'] for row in hist_rows]).tolist())
                    paired = []
                    for row in june_rows:
                        stamp = row['timestamp']
                        loc_prediction = float(next(loc_predictions)) if row['location_features'] is not None else None
                        hist_prediction = float(next(hist_predictions)) if row['history_features'] is not None else None
                        hist_available = row['history_available']
                        if use_baseline:
                            prediction = predict(values, profile, stamp, baseline_method)
                            hist_prediction, hist_available = prediction if prediction is not None else (None, None)
                        scored = row['actual'] is not None and loc_prediction is not None and hist_prediction is not None
                        saved = {'site_id': site, 'target': target, 'timestamp_local': stamp.isoformat(), 'actual_kw': row['actual'],
                                 'location_prediction_kw': loc_prediction, 'history_prediction_kw': hist_prediction,
                                 'location_available_at_local': row['location_available'].isoformat() if row['location_available'] else None,
                                 'history_available_at_local': hist_available.isoformat() if hist_available else None,
                                 'paired_scored': scored}
                        all_predictions.append(saved)
                        if scored:
                            paired.append(saved)
                    if not paired:
                        raise ValueError('No paired June predictions')
                    truth = [row['actual_kw'] for row in paired]
                    hist = [row['history_prediction_kw'] for row in paired]
                    loc = [row['location_prediction_kw'] for row in paired]
                    comparison = compare_modes(truth, hist, loc)
                    comparison.update({'site_id': site, 'target': target, 'unit': 'kW', 'calendar_hours': len(june_rows),
                                       'paired_hours': len(paired), 'history_selection': history_info,
                                       'location_model_file': location_info['model_file'],
                                       'location_training_site_ids': training_sites, 'excluded_site_group': heldout,
                                       'location_negative_predictions': sum(value < 0 for value in loc),
                                       'location_clipped_diagnostic_scores': asdict(score(truth, [max(0., value) for value in loc]))})
                    report['groups'].append(comparison)
                    print(f'Compared {site} {target}: history {comparison["history_based"]["nmae"]:.1%}; location-only {comparison["location_only"]["nmae"]:.1%}.', flush=True)
    report['source_unchanged'] = file_sha256(args.archive) == report['source_sha256']
    if not report['source_unchanged']:
        raise ValueError('Source changed during experiment')
    (args.output_dir / 'results.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    with (args.output_dir / 'predictions.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_predictions[0])); writer.writeheader(); writer.writerows(all_predictions)
    lines = ['# Location-only versus history-based input comparison', '',
             'User-approved six-site trial: fit April, choose settings on May, refit April-May, evaluate June.',
             'Location-only holds the evaluated site/group out of fitting and tuning. Lower nMAE is better.', '',
             '| Site | Target | Paired June hours | History-based nMAE | Location-only nMAE | Gap in percentage points |',
             '| --- | --- | ---: | ---: | ---: | ---: |']
    for group in report['groups']:
        lines.append(f'| {group["site_id"]} | {group["target"]} | {group["paired_hours"]} | {group["history_based"]["nmae"]:.1%} | {group["location_only"]["nmae"]:.1%} | {100*group["nmae_gap"]:+.1f} |')
    lines.extend(['', '## Limits', ''] + ['- '+value for value in report['limitations']])
    lines.append('- Acceptance limits remain unset; no input mode was approved automatically.')
    (args.output_dir / 'summary.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('Saved nested site/time comparison. July unscored; no deployment decision made.')


if __name__ == '__main__':
    main()

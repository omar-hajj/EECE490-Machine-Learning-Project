"""Independently reconstruct net targets and replay the saved P90 model."""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import csv
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    import joblib
    import numpy as np
    from threadpoolctl import threadpool_limits
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--archive', required=True, type=Path)
    args = parser.parse_args()
    report = json.loads((args.output_dir / 'results.json').read_text())
    require(not report['test_period_scored'] and not report['generator_recommendations_generated'], 'Unexpected dispatch/test claim')
    require(sha(args.archive) == report['source_sha256'], 'Source changed')
    require(sha(args.baseline_dir / 'hourly_data.csv') == report['input_sha256']['hourly_data.csv'], 'Prepared data changed')
    model_path = args.output_dir / 'azm_signed_net_p90.joblib'
    require(sha(model_path) == report['model_sha256'], 'Saved model changed')
    channels = defaultdict(dict)
    with (args.baseline_dir / 'hourly_data.csv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['site_id'] == 'azm':
                channels[row['target']][datetime.fromisoformat(row['timestamp_local_unverified'])] = float(row['value_source_units'])
    net = {time: value - channels['pv'][time] for time, value in channels['load'].items() if time in channels['pv']}
    start, end = (datetime.fromisoformat(report[name]) for name in ('validation_start', 'validation_end_exclusive'))
    require(all(time < end for time in net), 'Test values in net series')
    profile = defaultdict(list)
    for time, value in net.items():
        if time < start:
            profile[(time.weekday(), time.hour)].append(value)
    model = joblib.load(model_path)
    q = report['quantile']
    require(model.named_steps['quantile'].get_params()['quantile_alpha'] == q, 'Wrong quantile')
    actual, predicted, prior = [], [], []
    with threadpool_limits(limits=1), (args.output_dir / 'validation_predictions.csv').open(encoding='utf-8', newline='') as stream:
        seen = set()
        for row in csv.DictReader(stream):
            time = datetime.fromisoformat(row['timestamp_local'])
            require(start <= time < end and time not in seen, 'Invalid/repeated validation hour')
            seen.add(time)
            observed = float(row['actual_signed_net_kw'])
            require(observed == net[time], 'Net target is not campus load minus PV')
            inputs = {'hour_of_week': str(time.weekday() * 24 + time.hour)}
            availability = []
            for lag in report['configuration']['lag_hours']:
                source_hour = time - timedelta(hours=lag)
                inputs[f'lag_{lag}h'] = net[source_hour]
                availability.append(source_hour + timedelta(hours=1))
            require(max(availability) <= time.replace(hour=0), 'Future input used')
            require(row['latest_input_available_at_local'] == max(availability).isoformat(), 'Availability label differs')
            estimate = float(row['upper_signed_net_kw'])
            require(math.isclose(float(model.predict([inputs])[0]), estimate, rel_tol=1e-9, abs_tol=1e-8), 'Saved prediction differs')
            weekday = float(np.quantile(profile[(time.weekday(), time.hour)], q, method='linear'))
            require(math.isclose(weekday, float(row['weekday_p90_baseline_kw']), rel_tol=1e-12), 'Weekday quantile differs')
            actual.append(observed)
            predicted.append(estimate)
            prior.append(weekday)
    require(len(actual) == report['common_validation_hours'], 'Coverage denominator differs')
    for values, key in ((predicted, 'model_scores'), (prior, 'weekday_quantile_baseline_scores')):
        residuals = [a - p for a, p in zip(actual, values)]
        loss = math.fsum(max(q * value, (q - 1) * value) for value in residuals) / len(residuals)
        coverage = sum(value <= 0 for value in residuals) / len(residuals)
        require(math.isclose(loss, report[key]['pinball_loss'], rel_tol=1e-12), 'Pinball loss differs')
        require(coverage == report[key]['empirical_hourly_coverage'], 'Empirical coverage differs')
    print('Verified signed net target, saved P90 predictions, pinball losses, measured coverage, midnight inputs and final-test exclusion.')


if __name__ == '__main__':
    main()

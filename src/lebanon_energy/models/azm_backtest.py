"""Earlier-only Azm checks and split July calibration; September is never loaded."""
import argparse
import csv
from dataclasses import asdict
from datetime import datetime
import json
import math
from pathlib import Path

from ..data.preparation import file_sha256
from ..models.baselines import fit_weekday_profile, predict
from ..evaluation.metrics import score
from ..models.quantiles import quantile_scores, signed_net_series
from ..models.ridge import build_rows, load_inputs, make_pipeline


def quantile_model(parameters):
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.pipeline import Pipeline
    from xgboost import XGBRegressor
    return Pipeline([('vectorizer', DictVectorizer(sparse=False)),
                     ('quantile', XGBRegressor(objective='reg:quantileerror', quantile_alpha=.9,
                      tree_method='hist', n_jobs=1, random_state=42, min_child_weight=5,
                      reg_lambda=1, **parameters))])


def residual_correction(residuals, quantile=.9):
    """Finite-sample upper order statistic; time dependence prevents a guarantee."""
    values = sorted(float(value) for value in residuals)
    if not values or not all(math.isfinite(value) for value in values) or not 0 < quantile < 1:
        raise ValueError('Finite residuals and a valid quantile are required')
    rank = math.ceil((len(values) + 1) * quantile)
    if rank > len(values):
        raise ValueError('Too few calibration observations')
    return values[rank - 1]


def fit(model, rows):
    if len(rows) < 2:
        raise ValueError('Insufficient earlier training data')
    model.fit([row['features'] for row in rows], [row['actual'] for row in rows])
    return model


def usable(rows):
    return [row for row in rows if row['features'] is not None and row['actual'] is not None]


def main():
    import joblib
    from threadpoolctl import threadpool_limits
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-dir', type=Path, default=Path('outputs/baselines_confirmed_azm'))
    parser.add_argument('--output-dir', type=Path, default=Path('outputs/azm_backtest'))
    args = parser.parse_args()
    source, _, all_series, _ = load_inputs(args.baseline_dir)
    series = {target: all_series[('azm', target)] for target in ('load', 'pv')}
    net = signed_net_series(series['load'], series['pv'])
    fixed_parameters = dict(max_depth=2, n_estimators=200, learning_rate=.05)
    report = {'source_sha256': source['source_sha256'], 'test_period_scored': False,
              'backtest_policy': 'Fixed Ridge alpha=1 and XGB depth=2, trees=200, rate=.05; no August-selected parameters.',
              'point_backtests': [], 'net_p90_backtests': []}
    predictions = []
    with threadpool_limits(limits=1):
        for month in (5, 6, 7):
            start, end = datetime(2026, month, 1), datetime(2026, month + 1, 1)
            for target, values in {**series, 'signed_net': net}.items():
                train, validation = build_rows(values, start, end, (24, 168))
                profile = fit_weekday_profile(values, start)
                rows = [row for row in usable(validation) if predict(values, profile, row['timestamp'], 'weekday_average')]
                model = fit(quantile_model(fixed_parameters) if target == 'signed_net' else make_pipeline(1.), train)
                estimates = model.predict([row['features'] for row in rows]).tolist()
                truth = [row['actual'] for row in rows]
                entry = {'target': target, 'start': start.isoformat(), 'end_exclusive': end.isoformat(),
                         'training_rows': len(train), 'training_last_target': train[-1]['timestamp'].isoformat()}
                if target == 'signed_net':
                    entry['scores'] = quantile_scores(truth, estimates, .9)
                    report['net_p90_backtests'].append(entry)
                else:
                    entry['ridge_scores'] = asdict(score(truth, estimates))
                    baseline = [predict(values, profile, row['timestamp'], 'weekday_average')[0] for row in rows]
                    entry['weekday_average_scores'] = asdict(score(truth, baseline))
                    report['point_backtests'].append(entry)
                for row, estimate in zip(rows, estimates):
                    predictions.append({'experiment': 'fixed_backtest', 'target': target,
                        'timestamp_local': row['timestamp'].isoformat(), 'actual': row['actual'], 'prediction': estimate,
                        'latest_input_available_at': row['available_at'].isoformat()})

        # Select on June only, then refit through June 30. July labels never fit the model.
        june, july, august = datetime(2026, 6, 1), datetime(2026, 7, 1), datetime(2026, 8, 1)
        train, validation = build_rows(net, june, july, (24, 168))
        rows = usable(validation)
        search = []
        parameters = json.loads(Path('config/quantile.json').read_text())['candidate_parameters']
        for params in parameters:
            model = fit(quantile_model(params), train)
            scores = quantile_scores([r['actual'] for r in rows], model.predict([r['features'] for r in rows]).tolist(), .9)
            search.append({'parameters': params, 'scores': scores})
        selected = min(search, key=lambda item: item['scores']['pinball_loss'])['parameters']
        train, validation = build_rows(net, july, august, (24, 168))
        model = fit(quantile_model(selected), train)
        rows = usable(validation)
        estimates = model.predict([r['features'] for r in rows]).tolist()
        split = datetime(2026, 7, 16)
        calibration = [(r, p) for r, p in zip(rows, estimates) if r['timestamp'] < split]
        evaluation = [(r, p) for r, p in zip(rows, estimates) if r['timestamp'] >= split]
        correction = residual_correction([r['actual'] - p for r, p in calibration])
        truth, raw = [r['actual'] for r, _ in evaluation], [p for _, p in evaluation]
        report['calibration'] = {'selection_period': 'June 2026', 'parameter_search': search,
            'selected_parameters': selected, 'training_last_target': train[-1]['timestamp'].isoformat(),
            'calibration_start': july.isoformat(), 'calibration_end_exclusive': split.isoformat(),
            'evaluation_end_exclusive': august.isoformat(), 'calibration_hours': len(calibration),
            'additive_correction_kw': correction, 'raw_scores': quantile_scores(truth, raw, .9),
            'adjusted_scores': quantile_scores(truth, [p + correction for p in raw], .9),
            'limitation': 'Empirical hourly coverage only; dependent time series and changing demand provide no coverage guarantee.'}
        for row, estimate in zip(rows, estimates):
            predictions.append({'experiment': 'calibration' if row['timestamp'] < split else 'calibration_check',
                'target': 'signed_net', 'timestamp_local': row['timestamp'].isoformat(), 'actual': row['actual'],
                'prediction': estimate, 'adjusted_prediction': estimate + correction if row['timestamp'] >= split else None,
                'latest_input_available_at': row['available_at'].isoformat()})

        # Demo point model: alpha chosen on June; refit before August; no August selection.
        train, validation = build_rows(series['load'], june, july, (24, 168))
        rows = usable(validation)
        alpha_search = []
        for alpha in (.1, 1., 10., 100., 1000.):
            candidate = fit(make_pipeline(alpha), train)
            measured = score([r['actual'] for r in rows], candidate.predict([r['features'] for r in rows]).tolist())
            alpha_search.append({'alpha': alpha, 'mae': measured.mae})
        alpha = min(alpha_search, key=lambda r: r['mae'])['alpha']
        train, _ = build_rows(series['load'], august, august, (24, 168))
        bundle = {'model': fit(make_pipeline(alpha), train), 'training_end_exclusive': august,
            'profiles': {target: fit_weekday_profile(values, august) for target, values in series.items()},
            'alpha': alpha, 'selection_period': 'June 2026', 'source_sha256': source['source_sha256']}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, args.output_dir / 'azm_demo.joblib')
    joblib.dump(model, args.output_dir / 'july_p90.joblib')
    report['demo_bundle'] = {'training_end_exclusive': august.isoformat(), 'alpha_search': alpha_search,
        'selected_alpha': alpha, 'model_sha256': file_sha256(args.output_dir / 'azm_demo.joblib')}
    report['input_sha256'] = file_sha256(args.baseline_dir / 'hourly_data.csv')
    report['code_sha256'] = file_sha256(Path(__file__))
    (args.output_dir / 'results.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    fields = list(dict.fromkeys(key for row in predictions for key in row))
    with (args.output_dir / 'predictions.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(predictions)
    print(json.dumps(report['calibration'], indent=2))


if __name__ == '__main__':
    main()

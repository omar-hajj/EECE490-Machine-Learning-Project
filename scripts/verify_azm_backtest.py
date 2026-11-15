"""Replay the July predictions, correction and chronology of the earlier-month backtests.

The served API model is checked by tests/test_api.py and scripts/evaluate_missing_inputs.py.
"""
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import joblib
from lebanon_energy.data.preparation import file_sha256
from lebanon_energy.features.history import history_calendar_features
from lebanon_energy.models.quantiles import signed_net_series
from lebanon_energy.models.ridge import load_inputs


def main(archive=None):
    directory = Path('outputs/azm_backtest')
    report = json.loads((directory / 'results.json').read_text())
    _, _, series, _ = load_inputs('outputs/baselines_confirmed_azm')
    print('Prepared inputs loaded.', flush=True)
    net = signed_net_series(series[('azm', 'load')], series[('azm', 'pv')])
    with (directory / 'predictions.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        stamp = datetime.fromisoformat(row['timestamp_local'])
        assert stamp < datetime(2026, 8, 1)
        assert datetime.fromisoformat(row['latest_input_available_at']) <= stamp.replace(hour=0)
    for entry in report['point_backtests'] + report['net_p90_backtests']:
        assert entry['training_last_target'] < entry['start']
    model = joblib.load(directory / 'july_p90.joblib')
    residuals = []
    evaluation = []
    july_rows = [row for row in rows if row['experiment'] in ('calibration', 'calibration_check')]
    features = [history_calendar_features(net, datetime.fromisoformat(row['timestamp_local']))[0]
                for row in july_rows]
    replayed = model.predict(features).tolist()
    print('July P90 predictions replayed.', flush=True)
    for row, prediction in zip(july_rows, replayed):
        stamp = datetime.fromisoformat(row['timestamp_local'])
        actual = net[stamp]
        assert abs(prediction - float(row['prediction'])) < 1e-5
        assert actual == float(row['actual'])
        if row['experiment'] == 'calibration':
            assert stamp < datetime(2026, 7, 16)
            residuals.append(actual - prediction)
        else:
            assert stamp >= datetime(2026, 7, 16)
            evaluation.append((actual, prediction, float(row['adjusted_prediction'])))
    import math
    correction = sorted(residuals)[math.ceil((len(residuals)+1)*.9)-1]
    assert correction == report['calibration']['additive_correction_kw']
    for actual, raw, adjusted in evaluation:
        assert abs(adjusted - raw - correction) < 1e-8
    for name, column in [('raw_scores', 1), ('adjusted_scores', 2)]:
        coverage = sum(r[0] <= r[column] for r in evaluation) / len(evaluation)
        assert coverage == report['calibration'][name]['empirical_hourly_coverage']
    assert file_sha256(directory / 'azm_demo.joblib') == report['demo_bundle']['model_sha256']
    if archive is not None:
        assert file_sha256(archive) == report['source_sha256']
    print('July P90 replay, calibration split/metrics and input timing'
          + (', source hash' if archive is not None else '') + ' verified; final tests unscored.')


if __name__ == '__main__':
    import numpy
    import xgboost
    from threadpoolctl import threadpool_limits
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, help='Data ZIP; when given, its hash is checked too')
    arguments = parser.parse_args()
    with threadpool_limits(limits=1):
        main(arguments.archive)

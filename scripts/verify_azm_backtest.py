"""Replay the July predictions, correction, point API model and chronology."""
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import joblib
from fastapi.testclient import TestClient
from lebanon_energy.api import create_app
from lebanon_energy.baselines import file_sha256
from lebanon_energy.features import history_calendar_features
from lebanon_energy.quantiles import signed_net_series
from lebanon_energy.ridge import load_inputs


def main():
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
    bundle = joblib.load(directory / 'azm_demo.joblib')
    assert file_sha256(directory / 'azm_demo.joblib') == report['demo_bundle']['model_sha256']
    issue = datetime(2026, 8, 1)
    readings = [{'timestamp_local': stamp.isoformat(), 'load_kw': value}
                for stamp, value in series[('azm', 'load')].items()
                if issue - timedelta(days=8) <= stamp < issue]
    client = TestClient(create_app(bundle))
    assert client.get('/health').status_code == 200
    response = client.post('/forecast', json={'issue_time_local': issue.isoformat(), 'readings': readings})
    print('Real-model API request completed.', flush=True)
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data['hourly']) == 24
    assert not data['generator_advice']['available']
    for row in data['hourly']:
        if row['load_method'] == 'ridge':
            stamp = datetime.fromisoformat(row['timestamp_local'])
            features, _ = history_calendar_features(series[('azm', 'load')], stamp)
            assert abs(row['load_kw'] - float(bundle['model'].predict([features])[0])) < 1e-8
    (directory / 'example_request.json').write_text(json.dumps({'issue_time_local': issue.isoformat(), 'readings': readings}, indent=2))
    (directory / 'example_response.json').write_text(json.dumps(data, indent=2))
    assert file_sha256(Path('Data for EECE 490 Project (1).zip')) == report['source_sha256']
    print('July P90 replay, calibration split/metrics, input timing, real-model API request and source hash verified; final tests unscored.')


if __name__ == '__main__':
    import numpy
    import xgboost
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        main()

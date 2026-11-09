"""Replay the nested location-only experiment without its feature/training helpers."""

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
import csv
import hashlib
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def measurements(actual, predicted):
    errors = [abs(p-a) for a,p in zip(actual,predicted)]
    mean = math.fsum(actual)/len(actual)
    mae = math.fsum(errors)/len(errors)
    return {'observations':len(actual), 'mae':mae, 'rmse':math.sqrt(math.fsum(value*value for value in errors)/len(errors)),
            'maximum_absolute_error':max(errors), 'mean_actual':mean, 'nmae':mae/mean if mean else None}


def check_scores(expected, saved):
    for key,value in expected.items():
        require(saved[key] is None if value is None else math.isclose(value,saved[key],rel_tol=1e-9,abs_tol=1e-10), 'Score differs: '+key)


def main():
    import joblib
    import numpy as np
    from sklearn.base import clone
    from threadpoolctl import threadpool_limits

    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-dir',required=True,type=Path)
    parser.add_argument('--result-dir',required=True,type=Path)
    parser.add_argument('--baseline-dir',required=True,type=Path)
    parser.add_argument('--archive',required=True,type=Path)
    args=parser.parse_args()
    report=json.loads((args.result_dir/'results.json').read_text(encoding='utf-8'))
    metadata=json.loads((args.prepared_dir/'metadata.json').read_text(encoding='utf-8'))
    config=report['protocol']
    require(not report['final_test_scored'] and not report['municipality_included'],'Unapproved evaluation scope')
    require(sha(args.archive)==report['source_sha256'],'Source changed')
    for name,digest in report['input_sha256'].items():
        require(sha(args.prepared_dir/name)==digest,'Prepared input changed')
    series=defaultdict(dict)
    with (args.prepared_dir/'history_kw.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            series[(row['site_id'],row['target'])][datetime.fromisoformat(row['timestamp_local'])]=float(row['value_kw'])
    raw_count=0
    with (args.baseline_dir/'hourly_data.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            key=row['site_id'],row['target']
            if key in series:
                require(math.isclose(series[key][datetime.fromisoformat(row['timestamp_local_unverified'])],float(row['value_source_units'])*.001,rel_tol=1e-12,abs_tol=1e-14),'Unit conversion is not fixed W to kW')
                raw_count+=1
    require(raw_count==sum(len(values) for values in series.values()),'History row count differs')
    weather={}
    names=('forecast_temperature','forecast_humidity','forecast_cloud_cover','forecast_shortwave_radiation','forecast_diffuse_radiation','forecast_direct_radiation')
    with (args.prepared_dir/'weather_features.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            weather[datetime.fromisoformat(row['timestamp_local'])]=row
    latitude=metadata['village']['representative_latitude'];longitude=metadata['village']['representative_longitude']
    def inputs(site,target,stamp,mode):
        row=weather.get(stamp)
        if row is None:return None,None
        angle=2*math.pi*(stamp.timetuple().tm_yday-1)/365.25
        values={'latitude':latitude,'longitude':longitude,'hour_of_week':str(stamp.weekday()*24+stamp.hour),
                'day_of_year_sin':math.sin(angle),'day_of_year_cos':math.cos(angle),**{name:float(row[name]) for name in names}}
        available=datetime.fromisoformat(row['nominal_available_at_local'])
        if mode=='history':
            for lag in (24,168):
                source_hour=stamp-timedelta(hours=lag)
                if source_hour not in series[(site,target)]:return None,None
                values[f'lag_{lag}h']=series[(site,target)][source_hour]
                available=max(available,source_hour+timedelta(hours=1))
        require(available<=stamp.replace(hour=0),'Input unavailable at midnight')
        return values,available
    train_start,select_start,eval_start,eval_end=(datetime.fromisoformat(config[name]) for name in ('training_start','inner_validation_start','evaluation_start','evaluation_end_exclusive'))
    def rows(sites,target,start,end,mode):
        x,y=[],[]
        for site in sites:
            stamp=start
            while stamp<end:
                values,_=inputs(site,target,stamp,mode)
                actual=series[(site,target)].get(stamp)
                if values is not None and actual is not None:x.append(values);y.append(actual)
                stamp+=timedelta(hours=1)
        return x,y
    cache={}
    def verify_model(info,target,mode):
        path=(args.result_dir/info['model_file']).resolve()
        require(path.is_relative_to(args.result_dir.resolve()),'Model path escapes output directory')
        require(sha(path)==info['model_sha256'],'Model changed')
        model=joblib.load(path)
        sites=info['training_site_ids']
        if mode=='location_only':
            heldout=set(info['heldout_site_ids'])
            require(not heldout.intersection(sites) and not heldout.intersection(info['selection_site_ids']),'Target site used in fitting/tuning')
            require(not any('lag' in name or 'site' in name or 'scale' in name for name in model.named_steps['vectorizer'].get_feature_names_out()),'Forbidden location-only feature')
            pair={'household_1','household_2'}
            require(not pair.intersection(heldout) or pair<=heldout,'Duplicated source group crosses holdout')
        x_train,y_train=rows(sites,target,train_start,select_start,mode)
        x_may,y_may=rows(sites,target,select_start,eval_start,mode)
        x_refit,y_refit=rows(sites,target,train_start,eval_start,mode)
        require(len(x_train)==info['inner_training_rows'] and len(x_may)==info['inner_validation_rows'] and len(x_refit)==info['refit_rows'],'Training period/count mismatch')
        require(datetime.fromisoformat(info['last_refit_target'])<eval_start,'June target used in fitting')
        inner=clone(model).fit(x_train,y_train)
        check_scores(measurements(y_may,inner.predict(x_may).tolist()),info['selected_candidate']['may_scores'])
        require(math.isclose(info['selected_candidate']['may_scores']['mae'],min(item['may_scores']['mae'] for item in info['candidate_log']),rel_tol=1e-12),'Settings not chosen from May candidate results')
        refit=clone(model).fit(x_refit,y_refit)
        probe=[];stamp=eval_start
        while stamp<eval_end:
            values,_=inputs(sites[0],target,stamp,mode)
            if values is not None:probe.append(values)
            stamp+=timedelta(hours=1)
        require(np.allclose(model.predict(probe),refit.predict(probe),rtol=1e-8,atol=1e-9),'Saved model cannot be reproduced from declared pre-June sites/data')
        cache[info['model_file']]=model
        return model
    predictions=defaultdict(dict)
    with (args.result_dir/'predictions.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            key=row['site_id'],row['target'];stamp=datetime.fromisoformat(row['timestamp_local'])
            require(eval_start<=stamp<eval_end and stamp not in predictions[key],'Unexpected prediction timestamp')
            predictions[key][stamp]=row
    def profile(values,start,end):
        grouped=defaultdict(list)
        for stamp,value in values.items():
            if start<=stamp<end:grouped[(stamp.weekday(),stamp.hour)].append((stamp,value))
        return {key:(math.fsum(value for _,value in samples)/len(samples),max(stamp for stamp,_ in samples)+timedelta(hours=1)) for key,samples in grouped.items()}
    def baseline_value(values,prepared,stamp,method):
        if method=='weekday_average':return prepared.get((stamp.weekday(),stamp.hour))
        source=stamp-timedelta(hours=24 if method=='yesterday' else 168)
        return (values[source],source+timedelta(hours=1)) if source in values else None
    with threadpool_limits(limits=1):
        for info in report['location_models']:verify_model(info,info['target'],'location_only')
        for group in report['groups']:
            site,target=group['site_id'],group['target'];values=series[(site,target)]
            info=group['history_selection'];history_model=verify_model(info,target,'history')
            may_profile=profile(values,train_start,select_start)
            for method,saved in info['may_baseline_scores'].items():
                actual,prior=[],[];stamp=select_start
                while stamp<eval_start:
                    result=baseline_value(values,may_profile,stamp,method)
                    if stamp in values and result is not None:actual.append(values[stamp]);prior.append(result[0])
                    stamp+=timedelta(hours=1)
                check_scores(measurements(actual,prior),saved)
            selected=info['selected_baseline_method']
            require(info['may_baseline_scores'][selected]['mae']==min(result['mae'] for result in info['may_baseline_scores'].values()),'Wrong May baseline selection')
            require((info['selected_history_kind']=='baseline')==(info['may_baseline_scores'][selected]['mae']<=info['selected_candidate']['may_scores']['mae']),'History policy not selected on May')
            refit_profile=profile(values,train_start,eval_start)
            location_model=cache[group['location_model_file']]
            actual,hist,loc=[],[],[]
            require(len(predictions[(site,target)])==720,'Missing June calendar rows')
            for stamp,row in sorted(predictions[(site,target)].items()):
                observed=float(row['actual_kw']) if row['actual_kw'] else None
                require(observed==values.get(stamp),'Wrong actual target')
                location_x,location_at=inputs(site,target,stamp,'location_only')
                history_x,history_at=inputs(site,target,stamp,'history')
                location_prediction=float(row['location_prediction_kw']) if row['location_prediction_kw'] else None
                history_prediction=float(row['history_prediction_kw']) if row['history_prediction_kw'] else None
                expected=float(location_model.predict([location_x])[0]) if location_x else None
                require(expected is None if location_prediction is None else math.isclose(expected,location_prediction,rel_tol=1e-8,abs_tol=1e-9),'Location-only prediction differs')
                if info['selected_history_kind']=='baseline':
                    result=baseline_value(values,refit_profile,stamp,selected)
                    expected_history,history_at=result if result else (None,None)
                else:expected_history=float(history_model.predict([history_x])[0]) if history_x else None
                require(expected_history is None if history_prediction is None else math.isclose(expected_history,history_prediction,rel_tol=1e-8,abs_tol=1e-9),'History prediction differs')
                require(row['location_available_at_local']==location_at.isoformat(),'Weather availability differs')
                if history_at:require(row['history_available_at_local']==history_at.isoformat(),'History availability differs')
                paired=observed is not None and history_prediction is not None and location_prediction is not None
                require((row['paired_scored']=='True')==paired,'Wrong scoring flag')
                if paired:actual.append(observed);hist.append(history_prediction);loc.append(location_prediction)
            require(len(actual)==group['paired_hours'],'Paired denominator differs')
            check_scores(measurements(actual,hist),group['history_based'])
            check_scores(measurements(actual,loc),group['location_only'])
            require(math.isclose(group['nmae_gap'],group['location_only']['nmae']-group['history_based']['nmae'],rel_tol=1e-12),'Gap differs')
    for target in ('load','pv'):
        for stamp,row in predictions[('household_1',target)].items():
            require(row['location_prediction_kw']==predictions[('household_2',target)][stamp]['location_prediction_kw'],'Same location/time inputs produced site-conditioned output')
    print('Verified 12 paired June comparisons, fixed W-to-kW conversion, 22 saved/refitted models, May-only selection, held-out source exclusion and no July evaluation.')


if __name__=='__main__':main()

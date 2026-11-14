"""Independently recompute saved errors and prove split/model/input bookkeeping."""
import argparse
import json
import math
from pathlib import Path

import numpy as np

from honeycomb_studio.surrogate_reliability import TARGET, load_source, read_csv, sha256


def check_metrics(rows, expected):
    actual = np.array([float(r['actual_SEA_J_kg']) for r in rows])
    predicted = np.array([float(r['predicted_SEA_J_kg']) for r in rows])
    residual = predicted - actual
    absolute = abs(residual)
    percent = 100 * absolute[actual > 1.e-12] / actual[actual > 1.e-12]
    computed = {'n': len(rows), 'mae_J_kg': float(sum(absolute) / len(rows)),
                'rmse_J_kg': float(math.sqrt(sum(residual ** 2) / len(rows))),
                'r2': float(1 - sum(residual ** 2) / sum((actual - np.mean(actual)) ** 2)),
                'bias_J_kg': float(sum(residual) / len(rows)), 'max_abs_error_J_kg': float(max(absolute)),
                'mape_percent': float(np.mean(percent)), 'ape_q95_percent': float(np.quantile(percent, .95))}
    if 'interval_lower_J_kg' in rows[0]:
        low = np.array([float(r['interval_lower_J_kg']) for r in rows])
        high = np.array([float(r['interval_upper_J_kg']) for r in rows])
        if not np.isfinite([low, high]).all() or np.any(low > high):
            raise ValueError('Malformed saved intervals')
        computed.update(coverage=float(np.mean((low <= actual) & (actual <= high))),
                        mean_interval_width_J_kg=float(np.mean(high - low)))
    for key, value in computed.items():
        if not math.isclose(value, expected[key], rel_tol=1.e-10, abs_tol=1.e-10):
            raise ValueError('Saved metric disagrees with predictions: ' + key)
    return computed


def verify(study):
    def read(name):
        return json.loads((study / name).read_text(encoding='utf-8'))
    protocol = read('protocol.json')
    lock = read('model-lock.json')
    results = read('results.json')
    splits = read('split-ids.json')
    if sha256(study / 'research-models.joblib') != lock['model_sha256']:
        raise ValueError('Locked model bytes changed')
    if sha256(study / 'protocol.json') != lock['protocol_sha256']:
        raise ValueError('Protocol changed after lock')
    flat = [s for ids in splits.values() for s in ids]
    if len(flat) != 494 or len(set(flat)) != 494:
        raise ValueError('Overlapping/omitted split IDs')
    rows, _ = load_source(study / 'data/source.zip')
    original = {r['design_id']: r for r in rows}
    if set(splits['historical_test']) != {r['design_id'] for r in rows if r['role'] == 'test'}:
        raise ValueError('Historical test IDs entered another role')
    folds = read('nested-cv.json')
    dev_ids = {r['design_id'] for r in rows if r['role'] == 'development'}
    heldout = []
    for fold in folds['folds']:
        fitting, validation = set(fold['training_ids']), set(fold['heldout_ids'])
        if fitting & validation or fitting | validation != dev_ids:
            raise ValueError('Nested CV contains leakage or missing IDs')
        heldout.extend(fold['heldout_ids'])
    if not folds['complete'] or len(heldout) != 411 or set(heldout) != dev_ids:
        raise ValueError('Nested CV must predict each original development sample once')
    if len(set(heldout)) != len(heldout):
        raise ValueError('Repeated outer-heldout predictions')
    nested = read_csv(study / 'nested-oof-predictions.csv')
    if len(nested) != 411 or {r['design_id'] for r in nested} != dev_ids:
        raise ValueError('Nested prediction IDs differ from folds')
    for row in nested:
        if not math.isclose(float(row['actual_SEA_J_kg']), float(original[row['design_id']][TARGET]), rel_tol=1.e-12):
            raise ValueError('OOF truth differs from immutable archive')
    check_metrics(nested, results['nested_cv_selection_procedure'])
    for name, split_name, result_name in [('qualification', 'qualification', 'qualification'),
                                          ('historical-test', 'historical_test', 'historical_test')]:
        predictions = read_csv(study / (name + '-predictions.csv'))
        if len(predictions) != len(splits[split_name]) or {r['design_id'] for r in predictions} != set(splits[split_name]):
            raise ValueError('Evaluation prediction IDs differ from locked split')
        check_metrics(predictions, results[result_name]['regression'])
        accepted = [r for r in predictions if r['accepted'] == 'True']
        safety = results[result_name]['screening']
        if (len(accepted) != safety['accepted'] or
                sum(r['actual_deleted'] == 'True' for r in accepted) != safety['deleted_among_accepted']):
            raise ValueError('Screening evidence/count mismatch')
        for row in predictions:
            truth = original[row['design_id']]
            if (row['actual_deleted'] != truth['rear_skin_deleted'] or not math.isclose(
                    float(row['actual_SEA_J_kg']), float(truth[TARGET]), rel_tol=1.e-12)):
                raise ValueError('Evaluation truth differs from original archive')
    for name, expected in protocol['source_files'].items():
        # Saved paths were absolute. Snapshot layout starts at the repo package.
        path = Path(name)
        candidates = list((study / 'executed-source').rglob(path.name))
        if not any(sha256(candidate) == expected for candidate in candidates):
            raise ValueError('Executed source snapshot missing: ' + name)
    checksums = read('delivery-checksums.json')
    for name, expected in checksums.items():
        path = (study / name).resolve()
        path.relative_to(study.resolve())
        if sha256(path) != expected:
            raise ValueError('Sealed delivery checksum changed: ' + name)
    return {'status': 'verified', 'source_samples': 489, 'sequential_development': 5,
            'disjoint_split_ids': 494, 'outer_oof_samples': 411,
            'metrics_independently_recomputed': True, 'model_and_protocol_hashes_verified': True,
            'physical_validation': 'not_established'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.study.resolve()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Retrospective spatial-block stress test of an already selected model family.

This is a diagnostic, not another model-selection loop or a fresh test. Labels
are never used for spatial clustering. Every fitted model excludes its held-out
geometry cluster, and S1–S5 are excluded from this diagnostic entirely.
"""
import argparse
import json
from pathlib import Path

import joblib
import numpy as np
from sklearn.base import clone
from sklearn.cluster import KMeans
from threadpoolctl import threadpool_limits

from honeycomb_studio.surrogate_reliability import (
    BOUNDS,
    SEED,
    DesignDomain,
    arrays,
    load_source,
    regression_metrics,
    screening_counts,
    sha256,
    write_csv,
    write_json,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Spatial stress output must be new')
    lock = json.loads((args.study / 'model-lock.json').read_text(encoding='utf-8'))
    if sha256(args.study / 'research-models.joblib') != lock['model_sha256']:
        raise ValueError('Locked model checksum changed')
    bundle = joblib.load(args.study / 'research-models.joblib')
    rows, _ = load_source(args.study / 'data/source.zip')
    dev = [r for r in rows if r['role'] == 'development']
    x, y, z = arrays(dev)
    normalized = (x - BOUNDS[:, 0]) / np.diff(BOUNDS, axis=1).ravel()
    with threadpool_limits(limits=2):
        groups = KMeans(n_clusters=5, random_state=SEED, n_init=20).fit_predict(normalized)
    args.output.mkdir(parents=True)
    write_json(args.output / 'protocol.json', {'kind': 'retrospective_leave_geometry_cluster_out',
        'groups': 5, 'clustering_uses_labels': False, 'selected_family': bundle['regression_name'],
        'model_sha256': lock['model_sha256'], 'classifier_threshold': .1,
        'threshold_use': 'diagnostic_only_not_qualified_policy', 'test_labels_used': False,
        'sequential_S1_S5_used': False, 'study_source_sha256': sha256(Path(__file__)),
        'fold_ids': {str(group): [dev[i]['design_id'] for i in np.flatnonzero(groups == group)]
                     for group in range(5)}})
    predicted, probability, eligible = np.full(len(y), np.nan), np.full(len(y), np.nan), np.zeros(len(y), bool)
    folds = []
    with threadpool_limits(limits=2):
        for group in range(5):
            training, heldout = np.flatnonzero(groups != group), np.flatnonzero(groups == group)
            if set(training) & set(heldout):
                raise ValueError('Spatial holdout overlap')
            regressor = clone(bundle['regressor']).fit(x[training], y[training])
            classifier = clone(bundle['classifier']).set_params(cv=3).fit(x[training], z[training])
            predicted[heldout] = regressor.predict(x[heldout])
            probability[heldout] = classifier.predict_proba(x[heldout])[:, list(classifier.classes_).index(1)]
            domain = DesignDomain(x[training], z[training])
            eligible[heldout] = domain.evaluate(x[heldout])['eligible']
            folds.append({'cluster': group, 'n_train': len(training), 'n_heldout': len(heldout),
                          'metrics': regression_metrics(y[heldout], predicted[heldout]),
                          'diagnostic_screening': screening_counts(z[heldout], probability[heldout],
                                                                   eligible[heldout], .1)})
            write_json(args.output / 'spatial-folds.json', folds)
            print(json.dumps({'spatial_cluster': group, 'mae_J_kg': folds[-1]['metrics']['mae_J_kg']}), flush=True)
    records = [{'design_id': r['design_id'], 'geometry_cluster': int(groups[i]),
                'actual_SEA_J_kg': float(y[i]), 'predicted_SEA_J_kg': float(predicted[i]),
                'actual_deleted': bool(z[i]), 'p_delete': float(probability[i]),
                'inside_training_support': bool(eligible[i])} for i, r in enumerate(dev)]
    write_csv(args.output / 'spatial-oof-predictions.csv', records)
    result = {'status': 'retrospective_spatial_stress_diagnostic',
              'regression': regression_metrics(y, predicted),
              'screening_at_0_1_diagnostic': screening_counts(z, probability, eligible, .1),
              'in_training_support_count': int(eligible.sum()), 'total': len(y),
              'heldout_cluster_excluded_from_fit': True,
              'model_reselected': False, 'validated_optimum': False, 'fresh_fea_required': True}
    write_json(args.output / 'results.json', result)
    write_json(args.output / 'checksums.json', {str(p.relative_to(args.output)): sha256(p)
               for p in args.output.rglob('*') if p.is_file() and p.name != 'checksums.json'})
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()

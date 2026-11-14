"""Create a new fixed-8-ms study; never overwrite frozen models or claim physical validation."""
from __future__ import annotations

import argparse
import json
import math
import platform
import time
import warnings
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from scipy.stats import qmc
from sklearn.base import clone
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold, train_test_split
from threadpoolctl import threadpool_limits

from honeycomb_studio.surrogate_reliability import (
    BOUNDS,
    FEATURES,
    PROTOCOL,
    SEED,
    TARGET,
    DesignDomain,
    acquisition_mask,
    arrays,
    audit_rows,
    boolean,
    classification_candidates,
    conformal_radius,
    load_source,
    read_csv,
    regression_candidates,
    regression_metrics,
    release_gates,
    screening_counts,
    select_threshold,
    sha256,
    write_csv,
    write_json,
)


def sequential_rows(validation):
    """Exposed S1–S5 labels join development; repeated baseline never duplicates training."""
    comparison_path = validation / 'results-8ms-comparison.json'
    status_path = validation / 'status-3bc66c62749746a7839df1a87392d798.json'
    comparison = json.loads(comparison_path.read_text(encoding='utf-8'))
    catalog = json.loads(status_path.read_text(encoding='utf-8'))
    locked = {r['candidate_id']: r for r in read_csv(validation / 'locked-candidates.csv')}
    if comparison['workflow_run_id'] != 43566570839 or catalog['workflow_run_id'] != 43566570839:
        raise ValueError('Wrong S1–S5 verification workflow')
    ids = catalog['validation_context']['candidate_ids']
    if ids != ['S1', 'S2', 'S3', 'S4', 'S5', 'B0249']:
        raise ValueError('Unexpected candidate-to-shard mapping')
    measured = {r['candidate_id']: r for r in comparison['cases']}
    rows = []
    for candidate_id, shard in zip(ids, catalog['shards'], strict=True):
        if not shard.get('archive_verified') or len(shard.get('runs', [])) != 1:
            raise ValueError('Missing verified native archive')
        run = shard['runs'][0]
        summary, quality = run['summary'], run['quality']
        if quality.get('numerical_quality') != 'passed' or not quality.get('solver_completed'):
            raise ValueError('Numerical verification failed')
        result = measured[candidate_id]
        if (not result['archive_verified'] or result['numerical_quality'] != 'passed' or
                summary['rear_skin_deleted'] is not result['rear_skin_deleted'] or
                not math.isclose(summary[TARGET], result['actual_SEA_at_8ms_J_kg'], rel_tol=1.e-12)):
            raise ValueError('Catalog and comparison disagree')
        if candidate_id == 'B0249':
            continue
        model = shard['spec']['model']
        for key in FEATURES:
            if not math.isclose(float(model[key]), float(locked[candidate_id][key]), rel_tol=1.e-12):
                raise ValueError('Candidate geometry differs from frozen prediction')
        row = {'design_id': 'validation-' + candidate_id, 'role': 'sequential_development',
               **{key: model[key] for key in FEATURES}, TARGET: summary[TARGET],
               'core_dissipation_J': summary['core_dissipation_J'], 'core_mass_kg': summary['core_mass_kg'],
               'rear_skin_deleted': summary['rear_skin_deleted'], 'event_finished': summary['event_finished'],
               'duration': model['duration'], 'velocity_m_s': summary['velocity_m_s'],
               'numerical_passed': True, 'archive_verified_current': True,
               'damage_fields_complete': summary['damage_fields_complete'],
               'history_integrity_passed': summary['history_integrity_passed'],
               'solver_completed': summary['solver_completed'], 'ml_development_eligible': quality['ml_eligible']}
        rows.append(row)
    if len(rows) != 5:
        raise ValueError('Five real verified candidates required')
    audit_rows(rows)
    return rows, {'comparison_sha256': sha256(comparison_path), 'catalog_sha256': sha256(status_path),
                  'locked_inputs_sha256': sha256(validation / 'locked-candidates.csv'),
                  'role': 'exposed_sequential_development_not_post_update_validation'}


def cv_indices(labels, groups=None, seed=SEED):
    if groups is None:
        return list(StratifiedKFold(3, shuffle=True, random_state=seed).split(labels, labels))
    return list(StratifiedGroupKFold(3, shuffle=True, random_state=seed).split(labels, labels, groups))


def fit_candidate(estimator, x, y, groups, classification):
    model = clone(estimator)
    if classification:
        # Probability calibration must respect the same sequential-design groups.
        model.set_params(cv=cv_indices(y, groups=groups))
    return model.fit(x, y)


def select_model(x, y, labels, candidates, splits, *, classification=False, groups=None):
    records = []
    for name, estimator in candidates.items():
        prediction = np.full(len(y), np.nan)
        fold_scores = []
        for training, heldout in splits:
            if set(training) & set(heldout):
                raise ValueError('CV leakage')
            fitted = fit_candidate(estimator, x[training], y[training],
                                   None if groups is None else groups[training], classification)
            values = (fitted.predict_proba(x[heldout])[:, list(fitted.classes_).index(1)]
                      if classification else fitted.predict(x[heldout]))
            prediction[heldout] = values
            fold_scores.append(float(log_loss(y[heldout], values, labels=[0, 1])) if classification else
                               float(np.mean(np.abs(y[heldout] - values))))
        if not np.isfinite(prediction).all():
            raise ValueError('Incomplete/nonfinite cross-validation predictions')
        score = (float(log_loss(y, prediction, labels=[0, 1])) if classification else
                 float(np.mean(np.abs(y - prediction))))
        records.append({'name': name, 'score': score, 'fold_scores': fold_scores,
                        'metric': 'log_loss' if classification else 'mae_J_kg'})
    records.sort(key=lambda r: (r['score'], r['name']))
    name = records[0]['name']
    return fit_candidate(candidates[name], x, y, groups, classification), name, records


def nested_evaluation(dev, output, candidates):
    x, y, labels = arrays(dev)
    predictions = np.full(len(y), np.nan)
    records = []
    folds = list(StratifiedKFold(5, shuffle=True, random_state=SEED).split(x, labels))
    for fold, (training, heldout) in enumerate(folds):
        print(f'Nested regression {fold + 1}/5: selecting inside training fold', flush=True)
        model, name, scores = select_model(x[training], y[training], labels[training], candidates,
                                           cv_indices(labels[training]))
        prediction = model.predict(x[heldout])
        predictions[heldout] = prediction
        records.append({'fold': fold, 'selected': name, 'inner_scores': scores,
                        'training_ids': [dev[i]['design_id'] for i in training],
                        'heldout_ids': [dev[i]['design_id'] for i in heldout],
                        'metrics': regression_metrics(y[heldout], prediction)})
        write_json(output / 'nested-cv.json', {'folds': records, 'complete': fold == 4})
    write_csv(output / 'nested-oof-predictions.csv', [
        {'design_id': r['design_id'], 'actual_SEA_J_kg': float(y[i]),
         'predicted_SEA_J_kg': float(predictions[i]), 'rear_skin_deleted': bool(labels[i])}
        for i, r in enumerate(dev)])
    return regression_metrics(y, predictions)


def predict_bundle(bundle, x):
    info = bundle['domain'].evaluate(x)
    prediction = bundle['regressor'].predict(x)
    classifier = bundle['classifier']
    probability = classifier.predict_proba(x)[:, list(classifier.classes_).index(1)]
    half_width = bundle['interval_radius'] * info['interval_scale']
    accepted = (np.zeros(len(x), bool) if bundle['threshold'] is None else
                info['eligible'] & (probability <= bundle['threshold']))
    return prediction, probability, half_width, accepted, info


def evaluate_set(name, rows, bundle, output):
    x, y, labels = arrays(rows)
    prediction, probability, half_width, accepted, info = predict_bundle(bundle, x)
    metrics = regression_metrics(y, prediction, half_width)
    safety = screening_counts(labels, probability, info['eligible'], bundle['threshold'])
    safety.update(log_loss=float(log_loss(labels, probability, labels=[0, 1])),
                  brier=float(brier_score_loss(labels, probability)))
    write_csv(output / (name + '-predictions.csv'), [
        {'design_id': r['design_id'], 'actual_SEA_J_kg': float(y[i]), 'predicted_SEA_J_kg': float(prediction[i]),
         'absolute_error_J_kg': float(abs(y[i] - prediction[i])),
         'interval_lower_J_kg': float(prediction[i] - half_width[i]),
         'interval_upper_J_kg': float(prediction[i] + half_width[i]),
         'p_delete': float(probability[i]), 'actual_deleted': bool(labels[i]),
         'domain_eligible': bool(info['eligible'][i]), 'accepted': bool(accepted[i])}
        for i, r in enumerate(rows)])
    return {'regression': metrics, 'screening': safety}


def propose(bundle, dev, sequential, output):
    """Diverse FEA acquisition proposals, with explicit abstention from safety approval."""
    sampler = qmc.Sobol(4, scramble=True, seed=SEED)
    pool = qmc.scale(sampler.random_base2(14), BOUNDS[:, 0], BOUNDS[:, 1])
    # Use only geometry-valid inputs before calling feature transformers.
    throat = pool[:, 2] - pool[:, 3] * np.tan(np.deg2rad(pool[:, 0]))
    pool = pool[(throat > np.maximum(8 * pool[:, 1], .5)) & (pool[:, 3] > 8 * pool[:, 1])]
    all_known = dev + sequential
    known_x, known_y, known_deleted = arrays(all_known)
    known_normalized = (known_x - BOUNDS[:, 0]) / np.diff(BOUNDS, axis=1).ravel()
    from scipy.spatial import cKDTree
    known_tree = cKDTree(known_normalized)
    # Every observed failure, including held-out labels, can veto a future FEA
    # request. This additional restriction is not the previously evaluated rule.
    failed_tree = cKDTree(known_normalized[known_deleted == 1])
    records = []
    for start in range(0, len(pool), 256):
        x = pool[start:start + 256]
        info = bundle['domain'].evaluate(x)
        classifier = bundle['classifier']
        probability = classifier.predict_proba(x)[:, list(classifier.classes_).index(1)]
        normalized = (x - BOUNDS[:, 0]) / np.diff(BOUNDS, axis=1).ravel()
        known_distance = known_tree.query(normalized)[0]
        bad_distance = failed_tree.query(normalized)[0]
        keep = acquisition_mask(info['eligible'], probability, known_distance, bad_distance)
        if start % 2048 == 0:
            print(f'Candidate acquisition: screened {start}/{len(pool)}; retained {len(records)}', flush=True)
        if not keep.any():
            continue
        x, known_distance, bad_distance = x[keep], known_distance[keep], bad_distance[keep]
        # Inference of exact clipped-wall mass can be expensive near narrow throats.
        # Such unsupported/high-risk inputs have already been rejected above.
        pred, probability, width, accepted, info = predict_bundle(bundle, x)
        for i, point in enumerate(x):
            records.append({**dict(zip(FEATURES, map(float, point), strict=True)),
                            'predicted_SEA_J_kg': float(pred[i]), 'lower_SEA_J_kg': float(pred[i] - width[i]),
                            'upper_SEA_J_kg': float(pred[i] + width[i]), 'p_delete': float(probability[i]),
                            'frozen_policy_accepted': bool(accepted[i]),
                            'distance_to_known': float(known_distance[i]),
                            'distance_to_known_failure': float(bad_distance[i]),
                            'requires_fea': True, 'safety_certified': False})
    records.sort(key=lambda r: -r['lower_SEA_J_kg'])
    selected = []
    for row in records:
        point = np.array([row[k] for k in FEATURES])
        if any(np.linalg.norm((point - np.array([other[k] for k in FEATURES])) /
                              np.diff(BOUNDS, axis=1).ravel()) < .075 for other in selected):
            continue
        selected.append({'candidate_id': f'V5-{len(selected) + 1:02d}', **row})
        if len(selected) == PROTOCOL['candidate_count']:
            break
    write_csv(output / 'fea-proposals.csv', selected)
    best = max((r for r in all_known if not boolean(r['rear_skin_deleted'])), key=lambda r: float(r[TARGET]))
    result = {'count': len(selected), 'target_duration_s': .008, 'purpose': 'fresh_fea_validation',
              'status': 'research_proposals_not_validated_optima', 'safety_certified': False,
              'best_observed_intact_id': best['design_id'], 'best_observed_intact_SEA_J_kg': float(best[TARGET]),
              'predicted_lower_bound_exceeds_best_observed': any(
                  r['lower_SEA_J_kg'] > float(best[TARGET]) for r in selected),
              'additional_known_failure_veto_changes_policy': True,
              'optimized_point_interval_has_no_conditional_coverage_guarantee': True,
              'candidates': selected}
    write_json(output / 'fea-proposals.json', result)
    return result


def run(args):
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Output already exists; use a NEW directory')
    rows, audit = load_source(args.archive)
    sequential, receipt = sequential_rows(args.validation_dir)
    # Validate source + augmentation together to prevent repeated geometries/IDs.
    audit_rows(rows + sequential)
    output.mkdir(parents=True)
    source_files = [Path(__file__), Path(__import__('honeycomb_studio.surrogate_reliability',
                   fromlist=['__file__']).__file__),
                   Path(__file__).resolve().parents[1] / 'docs/research/SURROGATE_RELIABILITY_V5.md']
    candidates = regression_candidates()
    physics_audit = None
    if args.physics_energy:
        from honeycomb_studio import surrogate_physics
        from honeycomb_studio.surrogate_physics import deterministic_mass, physics_candidates
        candidates = physics_candidates()
        source_files.extend([Path(surrogate_physics.__file__),
            Path(__file__).resolve().parents[1] / 'docs/research/SURROGATE_RELIABILITY_V6_PHYSICS.md',
            Path(__file__).resolve().parents[1] / 'src/honeycomb_studio/campaign_ml.py',
            Path(__file__).resolve().parents[1] / 'src/honeycomb_studio/adapters/reentrant.py'])
        all_x, _, _ = arrays(rows + sequential)
        observed_mass = np.array([float(r['core_mass_kg']) for r in rows + sequential])
        relative = abs(deterministic_mass(all_x) / observed_mass - 1)
        if relative.max() > 1.e-10:
            raise ValueError('Geometry mass does not match the source FEA masses')
        physics_audit = {'count': len(relative), 'max_relative_mass_discrepancy': float(relative.max()),
                         'observed_mass_used_as_feature': False}
    protocol = {**PROTOCOL, 'regression_candidates': list(candidates),
                'classification_candidates': list(classification_candidates()),
                'source_files': {str(p): sha256(p) for p in source_files},
                'libraries': {p: version(p) for p in ('numpy', 'scipy', 'scikit-learn', 'joblib')},
                'python': platform.python_version(), 'source_audit': audit, 'augmentation': receipt,
                'physics_energy': args.physics_energy, 'deterministic_mass_audit': physics_audit,
                'qualification_status': 'exposed_retrospective_after_v5' if args.physics_energy else
                    'internal_retrospective_split_predeclared_before_fit'}
    if args.physics_energy:
        protocol['revision'] = 'reliability-v6-physics-energy'
    write_json(output / 'protocol.json', protocol)
    dev = [r for r in rows if r['role'] == 'development']
    historical = [r for r in rows if r['role'] == 'test']
    _, _, labels = arrays(dev)
    fit_indices, reserve = train_test_split(np.arange(len(dev)), test_size=.4, stratify=labels, random_state=SEED)
    calibration, qualification = train_test_split(reserve, test_size=.5, stratify=labels[reserve],
                                                 random_state=SEED + 1)
    split_ids = {'fitting_original': [dev[i]['design_id'] for i in fit_indices],
                 'fitting_sequential': [r['design_id'] for r in sequential],
                 'calibration': [dev[i]['design_id'] for i in calibration],
                 'qualification': [dev[i]['design_id'] for i in qualification],
                 'historical_test': [r['design_id'] for r in historical]}
    flattened = [s for group in split_ids.values() for s in group]
    if len(set(flattened)) != len(flattened):
        raise ValueError('Fitting/calibration/qualification overlap')
    write_json(output / 'split-ids.json', split_ids)
    print('Source checks passed. Protocol and disjoint splits locked before fitting.', flush=True)
    with warnings.catch_warnings(record=True) as captured, threadpool_limits(limits=2):
        warnings.simplefilter('always')
        nested = nested_evaluation(dev, output, candidates)
        fitting = [dev[i] for i in fit_indices] + sequential
        x, y, z = arrays(fitting)
        # S1–S5 are nearby and selected jointly: never scatter them over inner folds.
        groups = [r['design_id'] if r['role'] != 'sequential_development' else 'S1-S5-cluster' for r in fitting]
        splits = cv_indices(z, groups=np.asarray(groups))
        print('Selecting final regression using fitting data only', flush=True)
        regressor, reg_name, reg_scores = select_model(x, y, z, candidates, splits)
        print('Selecting/calibrating rear-deletion classifier using fitting data only', flush=True)
        classifier, cls_name, cls_scores = select_model(x, z, z, classification_candidates(), splits,
                                                       classification=True, groups=np.asarray(groups))
        write_json(output / 'fitting-selection.json', {'regression': reg_scores, 'classification': cls_scores,
                   'sequential_cluster_kept_in_one_inner_fold': True})
        domain = DesignDomain(x, z)
        cal_rows = [dev[i] for i in calibration]
        cal_x, cal_y, cal_z = arrays(cal_rows)
        info = domain.evaluate(cal_x)
        radius = conformal_radius(abs(regressor.predict(cal_x) - cal_y) / info['interval_scale'])
        if not math.isfinite(radius):
            raise ValueError('Insufficient interval calibration samples')
        cal_probability = classifier.predict_proba(cal_x)[:, list(classifier.classes_).index(1)]
        threshold, risk_table = select_threshold(cal_z, cal_probability, info['eligible'])
        write_csv(output / 'threshold-calibration.csv', risk_table)
        bundle = {'regressor': regressor, 'classifier': classifier, 'domain': domain,
                  'interval_radius': radius, 'threshold': threshold, 'regression_name': reg_name,
                  'classification_name': cls_name, 'protocol_sha256': sha256(output / 'protocol.json'),
                  'scope': 'fixed_8ms_exploratory', 'official_ml_eligible': False,
                  'physical_validated': False, 'split_ids': split_ids}
        joblib.dump(bundle, output / 'research-models.joblib')
        # Lock model + policy BEFORE evaluating qualification or historical labels.
        write_json(output / 'model-lock.json', {'model_sha256': sha256(output / 'research-models.joblib'),
                   'protocol_sha256': sha256(output / 'protocol.json'), 'threshold': threshold,
                   'regression': reg_name, 'classification': cls_name, 'interval_radius': radius,
                   'qualification_labels_used_for_selection': False,
                   'historical_test_used_for_selection': False})
        print('Model and threshold locked. Opening internal qualification labels.', flush=True)
        qualification_result = evaluate_set('qualification', [dev[i] for i in qualification], bundle, output)
        historical_result = evaluate_set('historical-test', historical, bundle, output)
        sequential_result = evaluate_set('sequential-fitting-diagnostic', sequential, bundle, output)
        proposals = propose(bundle, dev, sequential, output)
    write_json(output / 'training-warnings.json', [{'category': w.category.__name__, 'message': str(w.message)}
                                                  for w in captured])
    gates = release_gates(qualification_result['regression'], qualification_result['screening'])
    result = {'status': gates['status'], 'passed': gates['passed'], 'gates': gates,
              'nested_cv_selection_procedure': nested,
              'qualification': qualification_result, 'historical_test': historical_result,
              'sequential_fitting_diagnostic_not_validation': sequential_result,
              'selected_regressor': reg_name, 'selected_classifier': cls_name,
              'threshold': threshold, 'fea_proposals': proposals,
              'source_489_unchanged': True, 'frozen_v4_models_unchanged': True,
              'fresh_independent_post_update_fea_results': 0,
              'historical_exposure_limits_retrospective_validation': True,
              'binomial_and_conformal_assumptions_not_established_for_optimized_points': True}
    write_json(output / 'results.json', result)
    report = [
        '# Nâng cấp độ tin cậy ' + protocol['revision'] + ' — Lưu Xuân Khánh', '',
        'Phạm vi: SEA lõi tại 8 ms, 6,5 m/s; nghiên cứu số, chưa kiểm chứng vật lý.', '',
        f'Mô hình hồi quy: {reg_name}. Phân loại: {cls_name}.',
        f'MAE nested OOF của toàn quy trình chọn mô hình: {nested["mae_J_kg"]:.3f} J/kg.',
        f'MAE qualification: {qualification_result["regression"]["mae_J_kg"]:.3f} J/kg.',
        f'MAPE qualification: {qualification_result["regression"]["mape_percent"]:.3f}%.',
        f'Ngưỡng nhận có đủ bằng chứng trên calibration: {threshold}.', '',
        'Các điều kiện chưa đạt: ' + ', '.join(gates['failed']) + '.', '',
        'S1–S5 đã tham gia phát triển; sai số trên chúng không phải kiểm chứng bản mới.',
        '78 test là test lịch sử đã từng được xem. Qualification nội bộ chưa thay thế FEA mới.',
        'Không có nghiệm tối ưu đã được xác nhận. Không đổi nhãn, ngưỡng sau đánh giá hoặc dữ liệu gốc.',
        'Khoảng dự báo chỉ có ý nghĩa marginal khi các giả thiết phù hợp; không bảo đảm tại điểm tối ưu.',
        'Danh sách fea-proposals là đề xuất chạy kiểm chứng, không phải thiết kế an toàn đã chứng nhận.', '',
        'Tái lập bằng cùng archive, validation-dir và mã nguồn, vào một output mới.',
    ]
    (output / 'BAO_CAO_DO_TIN_CAY.md').write_text('\n'.join(report) + '\n', encoding='utf-8')
    write_json(output / 'checksums.json', {str(p.relative_to(output)): sha256(p) for p in output.rglob('*')
                                         if p.is_file() and p.name != 'checksums.json'})
    print(json.dumps({'output': str(output), 'status': result['status'], 'qualification_mae_J_kg':
                      qualification_result['regression']['mae_J_kg'], 'proposals': proposals['count']},
                     ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--validation-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--physics-energy', action='store_true', help='v6: audit and use geometry-exact mass')
    args = parser.parse_args()
    start = time.monotonic()
    was_new = not args.output.exists()
    try:
        run(args)
    except Exception as exc:
        if was_new and args.output.exists():
            write_json(args.output / 'run-error.json', {'error': repr(exc), 'elapsed_s': time.monotonic() - start})
        raise


if __name__ == '__main__':
    main()

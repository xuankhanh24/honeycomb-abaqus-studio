"""One bounded, immutable FEA verification of a locked research surrogate."""
from copy import deepcopy
from math import isclose, isfinite
from typing import Any

import numpy as np

from .duration_followup import _valid_result
from .horizon_summary import HORIZON_SAMPLE_TOLERANCE_S
from .models import BatchSpec, digest, expand

FEATURES = ('reentrant_delta_deg', 'foil', 'cell_size', 'reentrant_cell_height')


def validation_identity(config):
    return digest({'protocol': 'locked-surrogate-fea-verification-v1',
                   'model_sha256': config['model_sha256'], 'candidates': config['candidates']})[:32]


def plan_validation(source, duration, duration_run, config, execution_sha):
    """Read-only planning; leave the running duration workflow and ownership alone."""
    if (duration['id'] != config['duration_job_id'] or
            duration_run['id'] != duration.get('workflow_run_id') or
            duration_run['repository']['full_name'] != config['repository'] or
            duration_run.get('path') != '.github/workflows/abaqus-linux.yml' or
            duration_run.get('head_branch') != 'main'):
        raise ValueError('Wrong duration prerequisite identity')
    if duration_run['status'] != 'completed':
        return None
    if duration.get('status') not in ('review', 'completed'):
        return None
    if (source['id'] != config['source_job_id'] or source['input_hash'] != config['source_input_hash'] or
            digest(source['spec']) != source['input_hash']):
        raise ValueError('Original fixed-8-ms inputs changed')
    if len(duration.get('shards', [])) != 2:
        raise ValueError('Duration prerequisite matrix incomplete')
    for shard in duration['shards']:
        if _valid_result(shard, .012) is None or shard['runs'][0].get('restart_state', {}).get('available') is not True:
            return None
    candidates = config['candidates']
    if not 1 <= len(candidates) <= 6 or len({r['candidate_id'] for r in candidates}) != len(candidates):
        raise ValueError('Verification limited to six unique predeclared designs')
    designs = []
    for row in candidates:
        if row.get('safety_certified') is not False or row.get('requires_fea') is not True:
            raise ValueError('An unverified proposal must not claim safety')
        point = {key: row[key] for key in FEATURES}
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and isfinite(v)
                   for v in [*point.values(), row['predicted_SEA_J_kg'], row['p_delete'],
                             row['lower_SEA_J_kg'], row['upper_SEA_J_kg']]):
            raise ValueError('Invalid frozen prediction/design')
        if not 0 <= row['p_delete'] <= .1 or row['predicted_SEA_J_kg'] <= 0:
            raise ValueError('Proposal exceeds the acquisition screen')
        if not row['lower_SEA_J_kg'] <= row['predicted_SEA_J_kg'] <= row['upper_SEA_J_kg']:
            raise ValueError('Invalid frozen prediction interval')
        designs.append(point)
    if len({tuple(r[k] for k in FEATURES) for r in designs}) != len(designs):
        raise ValueError('Duplicate verification geometry')
    spec = deepcopy(source['spec'])
    spec['model'].update(duration=.012, field_intervals=1200, history_intervals=6000)
    spec.update(name='Reliability locked-model validation | reliability-20261114',
                notes='12-ms FEA with separately sealed 8-ms labels; no automatic training or optimality claim.',
                sampling='table', axes=[], designs=designs, max_runs=len(designs),
                runtime_budget_minutes=300, execution_mode='parallel', max_parallel_runs=len(designs),
                export_all_fields=False, data_profile='research', backup_after_run=False)
    spec = BatchSpec.model_validate(spec).model_dump()
    template = expand(BatchSpec.model_validate(source['spec']))[0]['resolved']
    derived = {'reentrant_inclined_length_mm', 'periodic_density_kg_m3', 'reentrant_indent',
               'reentrant_angle_to_z_deg'}
    for row in expand(BatchSpec.model_validate(spec)):
        model = row['resolved']
        changed = {k for k, v in template.items() if model[k] != v}
        if (changed - set(FEATURES) - derived - {'duration', 'field_intervals', 'history_intervals'} or
                not isclose(model['duration'], .012) or
                not isclose(model['duration'] / model['field_intervals'],
                            template['duration'] / template['field_intervals']) or
                not isclose(model['duration'] / model['history_intervals'],
                            template['duration'] / template['history_intervals']) or
                model['cpus'] != 4 or model['precision'] != template['precision']):
            raise ValueError('Verification changed locked physics/output settings')
    return {'id': validation_identity(config), 'name': spec['name'], 'profile': 'research',
            'status': 'draft', 'spec': spec, 'input_hash': digest(spec),
            'parameter_title': '12-ms FEA | distinct 8-ms surrogate verification',
            'validation_context': {'kind': 'locked-surrogate-fea-verification-v1',
                'expected_source_sha': execution_sha, 'model_sha256': config['model_sha256'],
                'study_protocol_sha256': config['study_protocol_sha256'],
                'candidate_ids': [r['candidate_id'] for r in candidates],
                'prediction_horizon_s': .008, 'simulation_duration_s': .012,
                'predictions': candidates, 'duration_prerequisite_job_id': duration['id'],
                'duration_prerequisite_workflow_id': duration_run['id'],
                'test_labels_used_for_fitting': False, 'automatic_retraining': False,
                'physical_validation': 'not_established', 'original_489_unchanged': True}}


def verification_report(parent, config):
    if parent['id'] != validation_identity(config) or digest(parent['spec']) != parent['input_hash']:
        raise ValueError('Verification request identity changed')
    context = parent['validation_context']
    if (context['model_sha256'] != config['model_sha256'] or context['predictions'] != config['candidates'] or
            context['candidate_ids'] != [r['candidate_id'] for r in config['candidates']]):
        raise ValueError('Frozen model/predictions changed after seeing FEA')
    models = expand(BatchSpec.model_validate(parent['spec']))
    shards = parent.get('shards', [])
    if len(shards) != len(models) or {s['index'] for s in shards} != set(range(len(models))):
        raise ValueError('Incomplete verification matrix')
    records: list[dict[str, Any]] = []
    for shard in sorted(shards, key=lambda s: s['index']):
        index = shard['index']
        if (digest(shard['spec']) != shard['input_hash'] or
                shard.get('parent_input_hash') != parent['input_hash'] or
                expand(BatchSpec.model_validate(shard['spec']))[0]['resolved'] != models[index]['resolved']):
            raise ValueError('Verification shard inputs changed')
        native = _valid_result(shard, .012)
        if native is None or shard['runs'][0].get('restart_state', {}).get('available') is not True:
            raise ValueError('Numerical/archive/restart evidence incomplete; no solver rerun requested')
        horizon = shard['runs'][0].get('research_horizon', {})
        if (horizon.get('available') is not True or horizon.get('horizon_s') != .008 or
                horizon.get('simulation_duration_s') != .012 or horizon.get('input_hash') != shard['input_hash'] or
                horizon.get('interpolated_deletion_label') is not False or
                set(horizon.get('source_sha256', {})) != {'impact_history.csv', 'rear-field-history.json'} or
                any(not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v)
                    for v in horizon.get('source_sha256', {}).values()) or
                set(horizon.get('native_sample_time_s', {})) != {'history', 'rear'} or
                any(not isinstance(v, (int, float)) or not isclose(v, .008, rel_tol=0,
                                                                 abs_tol=HORIZON_SAMPLE_TOLERANCE_S)
                    for v in horizon.get('native_sample_time_s', {}).values())):
            raise ValueError('No auditable 8-ms native subwindow; refusing to substitute 12-ms labels')
        actual = horizon['summary']
        if (not isclose(actual.get('last_time_s', 0), .008, abs_tol=HORIZON_SAMPLE_TOLERANCE_S, rel_tol=0) or
                not all(isinstance(actual.get(key), (int, float)) and isfinite(actual[key]) and actual[key] > 0
                        for key in ('SEA_core_J_kg', 'core_mass_kg', 'core_dissipation_J')) or
                not isclose(actual['SEA_core_J_kg'], actual['core_dissipation_J'] / actual['core_mass_kg'],
                            rel_tol=1.e-10) or not isinstance(native.get('core_mass_kg'), (int, float)) or
                not isclose(actual['core_mass_kg'], native['core_mass_kg'], rel_tol=1.e-10)):
            raise ValueError('Invalid fixed-8-ms SEA/mass/energy evidence')
        predicted = config['candidates'][index]
        if any(not isclose(models[index]['requested'][key], predicted[key], rel_tol=1.e-12) for key in FEATURES):
            raise ValueError('Candidate prediction does not match simulated geometry')
        sea = actual['SEA_core_J_kg']
        if any(not isinstance(row.get(key), bool) for row in (actual, native)
               for key in ('rear_skin_deleted', 'event_finished')):
            raise ValueError('Missing actual rear/event outcome')
        error = sea - predicted['predicted_SEA_J_kg']
        records.append({'candidate_id': predicted['candidate_id'], 'predicted_SEA_J_kg':
                        predicted['predicted_SEA_J_kg'], 'actual_SEA_at_8ms_J_kg': sea,
                        'absolute_error_J_kg': abs(error), 'absolute_percentage_error': 100 * abs(error) / sea,
                        'lower_SEA_J_kg': predicted['lower_SEA_J_kg'],
                        'upper_SEA_J_kg': predicted['upper_SEA_J_kg'],
                        'interval_contains_actual': predicted['lower_SEA_J_kg'] <= sea <= predicted['upper_SEA_J_kg'],
                        'predicted_p_delete': predicted['p_delete'],
                        'rear_skin_deleted': actual.get('rear_skin_deleted'),
                        'event_finished': actual.get('event_finished'), 'numerical_quality': 'passed',
                        'actual_SEA_at_12ms_J_kg': native['SEA_core_J_kg'],
                        'rear_skin_deleted_at_12ms': native['rear_skin_deleted'],
                        'event_finished_at_12ms': native['event_finished'],
                        'SEA_change_8_to_12_percent': 100 * (native['SEA_core_J_kg'] - sea) / native['SEA_core_J_kg'],
                        'native_restart_available': True})
    mae = sum(r['absolute_error_J_kg'] for r in records) / len(records)
    mape = sum(r['absolute_percentage_error'] for r in records) / len(records)
    tail = float(np.quantile([r['absolute_percentage_error'] for r in records], .95))
    coverage = sum(r['interval_contains_actual'] for r in records) / len(records)
    return {'kind': 'fresh_locked_model_fea_verification', 'model_sha256': config['model_sha256'],
            'cases': records, 'mae_J_kg': mae, 'mape_percent': mape,
            'ape_q95_percent': tail, 'interval_coverage': coverage,
            'rear_intact_count': sum(r['rear_skin_deleted'] is False for r in records),
            'fixed_horizon_targets_passed': mae <= 20 and mape <= 2 and tail <= 5 and coverage >= .9 and
                all(r['rear_skin_deleted'] is False for r in records),
            'verified_optimum': False, 'physical_validation': 'not_established',
            'automatic_retraining': False, 'original_489_unchanged': True,
            'prediction_horizon_s': .008, 'simulation_duration_s': .012, 'mixed_horizon_training': False,
            'interpretation': 'Six selected acquisition points do not certify a global failure rate or optimum.'}

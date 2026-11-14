"""Plan a bounded 12-ms validation from completed, immutable 8-ms results."""

import math
from copy import deepcopy

from .models import BatchSpec, digest, expand

GEOMETRY_KEYS = ('reentrant_delta_deg', 'foil', 'cell_size', 'reentrant_cell_height')


def _valid_result(shard, duration=.008):
    if shard.get('status') not in ('completed', 'review') or shard.get('archive_verified') is not True:
        return None
    runs = shard.get('runs', [])
    if len(runs) != 1:
        return None
    run = runs[0]
    summary = run.get('summary') or {}
    sea = summary.get('SEA_core_J_kg')
    last_time = summary.get('last_time_s')
    if (run.get('status') not in ('completed', 'review') or run.get('test_only') is True or
            (run.get('quality') or {}).get('numerical_quality') != 'passed' or
            summary.get('solver_completed') is not True or
            summary.get('history_integrity_passed') is not True or
            summary.get('damage_fields_complete') is not True or
            not isinstance(sea, (int, float)) or isinstance(sea, bool) or not math.isfinite(sea) or sea <= 0 or
            not isinstance(last_time, (int, float)) or not math.isfinite(last_time) or
            not math.isclose(last_time, duration, rel_tol=1.e-6, abs_tol=1.e-9)):
        return None
    return summary


def plan_followup(parent: dict, source_run: dict, config: dict, execution_sha: str):
    """Return None while the exact source workflow is running; never fit a model."""
    if (source_run['id'] != config['source_workflow_run_id'] or
            source_run['head_sha'] != config['source_sha'] or source_run['head_branch'] != 'main' or
            source_run['repository']['full_name'] != config['repository'] or
            source_run.get('path') != '.github/workflows/abaqus-linux.yml'):
        raise ValueError('Unexpected source workflow identity')
    if source_run['status'] != 'completed':
        return None
    if (parent['id'] != config['source_job_id'] or parent['input_hash'] != config['source_input_hash'] or
            digest(parent['spec']) != config['source_input_hash'] or
            parent.get('workflow_run_id') != config['source_workflow_run_id']):
        raise ValueError('Source catalog or requested input changed')
    expected = expand(BatchSpec.model_validate(parent['spec']))
    shards = parent.get('shards', [])
    if (len(shards) != len(config['candidate_ids']) or len(expected) != len(shards) or
            {s['index'] for s in shards} != set(range(len(shards)))):
        raise ValueError('Incomplete source design matrix')
    indexed = {}
    for shard in shards:
        index = shard['index']
        models = expand(BatchSpec.model_validate(shard['spec']))
        if (len(models) != 1 or models[0]['resolved'] != expected[index]['resolved'] or
                digest(shard['spec']) != shard['input_hash'] or
                shard.get('parent_input_hash') != parent['input_hash']):
            raise ValueError('Source shard inputs changed')
        if shard.get('status') not in ('completed', 'review') or shard.get('archive_verified') is not True:
            raise ValueError('Source matrix has unfinished or unarchived results')
        indexed[config['candidate_ids'][index]] = (shard, models[0], _valid_result(shard))
    baseline = indexed['B0249']
    if baseline[2] is None:
        raise ValueError('Baseline lacks a numerically valid 8-ms result')
    eligible = [(name, data) for name, data in indexed.items()
                if name != 'B0249' and data[2] is not None and data[2].get('rear_skin_deleted') is False]
    if not eligible:
        raise ValueError('No numerically valid, rear-intact candidate at 8 ms')
    selected, candidate = max(eligible, key=lambda item: item[1][2]['SEA_core_J_kg'])
    name = 'Duration verification 8-12 ms | B0249 + ' + selected
    spec = deepcopy(parent['spec'])
    model = deepcopy(baseline[1]['requested'])
    model.update(duration=.012, field_intervals=1200, history_intervals=6000)
    spec.update(name=name, notes='Independent duration verification; frozen 489 samples and fitted models unchanged.',
                model=model, sampling='table', axes=[],
                designs=[{key: entry[1]['requested'][key] for key in GEOMETRY_KEYS}
                         for entry in (baseline, candidate)],
                max_runs=2, runtime_budget_minutes=300, execution_mode='parallel', max_parallel_runs=2,
                export_all_fields=False, data_profile='research', backup_after_run=False)
    spec = BatchSpec.model_validate(spec).model_dump()
    for new, old in zip(expand(BatchSpec.model_validate(spec)), (baseline, candidate), strict=True):
        changed = {key for key in new['resolved'] if new['resolved'][key] != old[1]['resolved'][key]}
        if changed != {'duration', 'field_intervals', 'history_intervals'}:
            raise ValueError('Duration follow-up would alter additional model parameters')
    identity = digest({'protocol': 'duration-verification-v1', 'source_job': parent['id'],
                       'source_workflow': source_run['id']})[:32]
    return {'id': identity, 'name': name, 'profile': 'research', 'status': 'draft',
            'spec': spec, 'input_hash': digest(spec), 'parameter_title': 'B0249 + ' + selected + ' | 12 ms',
            'validation_context': {'kind': 'duration-verification-v1',
                'source_job_id': parent['id'], 'source_workflow_run_id': source_run['id'],
                'source_sha': source_run['head_sha'], 'source_input_hash': parent['input_hash'],
                'candidate_ids': ['B0249', selected], 'selected_by': 'highest measured 8-ms SEA among numerically valid rear-intact candidates',
                'selected_SEA_at_8ms_J_kg': candidate[2]['SEA_core_J_kg'],
                'baseline_SEA_at_8ms_J_kg': baseline[2]['SEA_core_J_kg'],
                'comparisons_at_ms': [8, 12], 'expected_source_sha': execution_sha,
                'restart_storage_required': True, 'models_refit': False, 'original_489_unchanged': True}}


def resource_recovery_indices(followup):
    """Retry only cases that never solved because hosted disk admission failed."""
    if followup.get('status') not in ('completed', 'review', 'blocked_environment'):
        raise ValueError('Resource recovery must wait for the entire current workflow')
    indices = []
    for shard in followup['shards']:
        if shard['status'] in ('completed', 'review') and shard.get('archive_verified') is True:
            if (_valid_result(shard, .012) is None or
                    shard['runs'][0].get('restart_state', {}).get('available') is not True):
                raise ValueError('Completed reference needs numerical/restart review before spending another solver run')
            continue
        if (shard['status'] == 'blocked_environment' and not shard.get('runs') and
                'insufficient CPU/RAM/disk' in (shard.get('error') or '')):
            indices.append(shard['index'])
        else:
            raise ValueError('A solver/upload/quality failure requires review; refusing an automatic solver rerun')
    if indices and followup.get('duration_resource_recovery_count', 0) >= 1:
        raise ValueError('The single authorized resource recovery attempt was already used')
    return indices


def validate_followup_inputs(source, followup, source_run, config):
    context = followup['validation_context']
    expected = plan_followup(source, source_run, config, context['expected_source_sha'])
    if (expected is None or followup['id'] != expected['id'] or followup['input_hash'] != expected['input_hash'] or
            digest(followup['spec']) != expected['input_hash'] or context != expected['validation_context']):
        raise ValueError('Follow-up inputs or source provenance changed')
    models = expand(BatchSpec.model_validate(followup['spec']))
    shards = followup.get('shards', [])
    if len(shards) != len(models) or {s['index'] for s in shards} != set(range(len(models))):
        raise ValueError('Incomplete follow-up matrix')
    for shard in shards:
        if (shard.get('parent_input_hash') != followup['input_hash'] or
                digest(shard['spec']) != shard['input_hash'] or
                expand(BatchSpec.model_validate(shard['spec']))[0]['resolved'] != models[shard['index']]['resolved']):
            raise ValueError('Follow-up shard inputs changed')
    return expected


def comparison_report(source: dict, followup: dict, source_run: dict, config: dict):
    """Compare measured horizons; a longer run is not experimental validation."""
    validate_followup_inputs(source, followup, source_run, config)
    context = followup['validation_context']
    shards = followup.get('shards', [])
    if len(shards) != 2 or {s['index'] for s in shards} != {0, 1}:
        raise ValueError('Incomplete 12-ms matrix')
    original = {config['candidate_ids'][s['index']]: _valid_result(s) for s in source['shards']}
    models = expand(BatchSpec.model_validate(followup['spec']))
    rows = []
    for shard in sorted(shards, key=lambda s: s['index']):
        name = context['candidate_ids'][shard['index']]
        if (digest(shard['spec']) != shard['input_hash'] or
                expand(BatchSpec.model_validate(shard['spec']))[0]['resolved'] != models[shard['index']]['resolved']):
            raise ValueError('12-ms shard inputs changed')
        short, long = original[name], _valid_result(shard, .012)
        if short is None or long is None or shard['runs'][0].get('restart_state', {}).get('available') is not True:
            raise ValueError('12-ms result or sealed restart state is not ready for ' + name)
        row = {'candidate_id': name, 'SEA_at_8ms_J_kg': short['SEA_core_J_kg'],
               'SEA_at_12ms_J_kg': long['SEA_core_J_kg'],
               'SEA_change_relative_to_12_percent':
                   100 * (long['SEA_core_J_kg'] - short['SEA_core_J_kg']) / long['SEA_core_J_kg'],
               'rear_skin_deleted_at_8ms': short.get('rear_skin_deleted'),
               'rear_skin_deleted_at_12ms': long.get('rear_skin_deleted'),
               'event_finished_at_8ms': short.get('event_finished'),
               'event_finished_at_12ms': long.get('event_finished')}
        for key in ('max_rear_downward_mm', 'end_contact_force_N', 'end_impactor_velocity_m_s',
                    'core_dissipation_J', 'maximum_energy_balance_drift_percent',
                    'maximum_artificial_energy_ratio_developed_percent'):
            row[key + '_at_8ms'] = short.get(key)
            row[key + '_at_12ms'] = long.get(key)
        a, b = short.get('max_rear_downward_mm'), long.get('max_rear_downward_mm')
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (a, b)):
            raise ValueError('Missing rear displacement for duration comparison')
        row['rear_displacement_change_relative_to_12_percent'] = 100 * (b - a) / max(abs(b), .02)
        row['rear_damage_changed'] = (
            short.get('rear_skin_deleted') != long.get('rear_skin_deleted') or
            short.get('deleted_elements_by_instance', {}).get('BOTTOM-1') !=
            long.get('deleted_elements_by_instance', {}).get('BOTTOM-1'))
        row['8ms_satisfies_duration_checks'] = (
            short.get('event_finished') is True and long.get('event_finished') is True and
            not row['rear_damage_changed'] and abs(row['SEA_change_relative_to_12_percent']) <= 2 and
            abs(row['rear_displacement_change_relative_to_12_percent']) <= 2)
        row['12ms_event_finished'] = long.get('event_finished') is True
        rows.append(row)
    return {'kind': 'measured-duration-comparison', 'source_workflow_run_id': source_run['id'],
            'followup_workflow_run_id': followup['workflow_run_id'], 'cases': rows,
            'comparison_tolerance_percent': 2, 'tolerance_status': 'project criterion, not an Abaqus standard',
            'physical_validation': 'not_established', 'models_refit': False, 'original_489_unchanged': True,
            'interpretation': '8-ms and 12-ms horizon comparison on two selected designs; no global time-convergence claim.'}

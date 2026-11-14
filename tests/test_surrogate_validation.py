"""Bounded fresh FEA dispatch must not disturb/recompute running duration jobs."""
import base64
import hashlib
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from honeycomb_studio.cloud_matrix import prepare, recover
from honeycomb_studio.models import BatchSpec, ModelSpec, digest, expand
from honeycomb_studio.surrogate_validation import plan_validation, validation_identity, verification_report


def fixture_data():
    spec = BatchSpec(model=ModelSpec(core_topology='reentrant_0', reentrant_geometry='angle', cpus=4,
                                    duration=.008, field_intervals=800, history_intervals=4000),
                     sampling='table', designs=[{'foil': .08}]).model_dump()
    source = {'id': 'a' * 32, 'spec': spec, 'input_hash': digest(spec)}
    long_spec = deepcopy(spec)
    long_spec['model'].update(duration=.012)
    long_spec['designs'] = [{'foil': .08}, {'foil': .09}]
    duration = prepare({'id': 'b' * 32, 'name': 'duration', 'profile': 'research', 'status': 'draft',
                        'spec': long_spec, 'input_hash': digest(long_spec)}, 999)
    duration['status'] = 'review'
    for shard in duration['shards']:
        shard.update(status='review', archive_verified=True, runs=[{
            'status': 'review', 'quality': {'numerical_quality': 'passed'},
            'restart_state': {'available': True},
            'summary': {'SEA_core_J_kg': 1000., 'solver_completed': True, 'history_integrity_passed': True,
                        'damage_fields_complete': True, 'last_time_s': .012,
                        'rear_skin_deleted': False, 'event_finished': False}}])
    config = {'repository': 'xuankhanh24/honeycomb-abaqus-studio', 'duration_job_id': duration['id'],
              'source_job_id': source['id'], 'source_input_hash': source['input_hash'],
              'model_sha256': 'c' * 64, 'study_protocol_sha256': 'd' * 64,
              'physics_sha256': {'fixture.py': hashlib.sha256(b'fixture').hexdigest()},
              'candidates': [{'candidate_id': 'V5-01', 'reentrant_delta_deg': 30., 'foil': .08,
                              'cell_size': 7., 'reentrant_cell_height': 4., 'predicted_SEA_J_kg': 1000.,
                              'lower_SEA_J_kg': 990., 'upper_SEA_J_kg': 1010.,
                              'p_delete': .03, 'safety_certified': False, 'requires_fea': True}]}
    run = {'id': 999, 'status': 'completed', 'path': '.github/workflows/abaqus-linux.yml',
           'head_branch': 'main', 'repository': {'full_name': config['repository']}}
    return source, duration, run, config


def test_plan_preserves_physics_and_leaves_duration_parent_unchanged():
    source, duration, run, config = fixture_data()
    before = deepcopy(duration)
    planned = plan_validation(source, duration, run, config, 'fixed-source')
    assert duration == before
    model = expand(BatchSpec.model_validate(planned['spec']))[0]['resolved']
    assert model['duration'] == .012 and model['cpus'] == 4
    assert model['history_intervals'] == 6000
    assert planned['validation_context']['prediction_horizon_s'] == .008
    assert planned['validation_context']['automatic_retraining'] is False
    assert planned['validation_context']['expected_source_sha'] == 'fixed-source'


def test_horizon_request_survives_a_manual_resource_recovery():
    source, duration, run, config = fixture_data()
    parent = prepare(plan_validation(source, duration, run, config, 'fixed-source'), 1000)
    assert parent['shards'][0]['research_horizon_s'] == .008
    parent['status'] = 'blocked_environment'
    parent['shards'][0]['status'] = 'blocked_environment'
    resumed = recover(parent, 1001)
    assert resumed['shards'][0]['research_horizon_s'] == .008


@pytest.mark.parametrize('state', ['running', 'resource_block', 'no_restart'])
def test_no_dispatch_until_entire_duration_and_recovery_are_finished(state):
    source, duration, run, config = fixture_data()
    if state == 'running':
        run['status'] = 'in_progress'
    elif state == 'resource_block':
        duration['status'] = 'blocked_environment'
    else:
        duration['shards'][1]['runs'][0]['restart_state']['available'] = False
    assert plan_validation(source, duration, run, config, 'new') is None


@pytest.mark.parametrize('problem', ['changed_physics', 'duplicate', 'unsafe_claim', 'nonfinite'])
def test_bad_or_unfrozen_proposals_are_rejected(problem):
    source, duration, run, config = fixture_data()
    if problem == 'changed_physics':
        source['spec']['model']['duration'] = .012
    elif problem == 'duplicate':
        config['candidates'].append({**config['candidates'][0], 'candidate_id': 'V5-02'})
    elif problem == 'unsafe_claim':
        config['candidates'][0]['safety_certified'] = True
    else:
        config['candidates'][0]['p_delete'] = float('nan')
    with pytest.raises(ValueError):
        plan_validation(source, duration, run, config, 'new')


def completed_verification():
    source, duration, run, config = fixture_data()
    parent = prepare(plan_validation(source, duration, run, config, 'fixed-source'), 1000)
    parent['status'] = 'review'
    result = deepcopy(duration['shards'][0]['runs'][0])
    result['summary'].update(last_time_s=.012, SEA_core_J_kg=1010., core_mass_kg=.02)
    result['research_horizon'] = {'available': True, 'horizon_s': .008, 'simulation_duration_s': .012,
        'input_hash': parent['shards'][0]['input_hash'], 'interpolated_deletion_label': False,
        'source_sha256': {'impact_history.csv': 'a' * 64, 'rear-field-history.json': 'b' * 64},
        'native_sample_time_s': {'history': .008, 'rear': .008},
        'summary': {'last_time_s': .008, 'SEA_core_J_kg': 1005., 'core_mass_kg': .02,
                    'core_dissipation_J': 20.1, 'rear_skin_deleted': False, 'event_finished': False}}
    parent['shards'][0].update(status='review', archive_verified=True, runs=[result])
    return parent, config


def test_successful_fresh_fea_does_not_claim_a_validated_optimum():
    parent, config = completed_verification()
    report = verification_report(parent, config)
    assert report['mae_J_kg'] == 5. and report['fixed_horizon_targets_passed']
    assert report['verified_optimum'] is False
    assert report['automatic_retraining'] is False
    assert report['interval_coverage'] == 1.


def test_fresh_interval_failure_cannot_be_hidden_by_good_average_error():
    parent, config = completed_verification()
    parent['shards'][0]['runs'][0]['research_horizon']['summary'].update(
        SEA_core_J_kg=1015., core_dissipation_J=20.3)
    report = verification_report(parent, config)
    assert report['mae_J_kg'] < 20
    assert report['interval_coverage'] == 0
    assert not report['fixed_horizon_targets_passed']


@pytest.mark.parametrize('problem', ['prediction_changed', 'no_restart', 'unarchived', 'wrong_input', 'no_8ms'])
def test_verification_never_hides_provenance_or_evidence_failures(problem):
    parent, config = completed_verification()
    if problem == 'prediction_changed':
        config['candidates'][0]['predicted_SEA_J_kg'] = 1005.
    elif problem == 'no_restart':
        parent['shards'][0]['runs'][0]['restart_state']['available'] = False
    elif problem == 'unarchived':
        parent['shards'][0]['archive_verified'] = False
    elif problem == 'no_8ms':
        del parent['shards'][0]['runs'][0]['research_horizon']
    else:
        parent['shards'][0]['spec']['model']['duration'] = .014
    with pytest.raises(ValueError):
        verification_report(parent, config)


@pytest.mark.parametrize('lost_response', [False, True])
def test_controller_dispatches_once_and_never_recomputes_duration(monkeypatch, lost_response):
    source, duration, run, config = fixture_data()
    scripts = Path(__file__).parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('reliability_dispatch_fixture', scripts / 'dispatch_reliability_validation.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    documents = {'jobs/' + source['id']: source, 'jobs/' + duration['id']: duration}
    posts = []
    before = deepcopy(duration)

    class Remote:
        repository = config['repository']

        def repo(self, method, route, body=None):
            if route.startswith('/actions/runs/'):
                return run
            if route == '/branches/main':
                return {'commit': {'sha': 'fixed-source'}}
            if route.startswith('/contents/'):
                return {'content': base64.b64encode(b'fixture').decode()}
            assert method == 'POST' and route.endswith('/dispatches')
            posts.append(body)
            if lost_response:
                raise RuntimeError('response lost after dispatch')

    class MemoryCatalog:
        def __init__(self, _):
            pass

        def get(self, key):
            return deepcopy(documents.get(key)), None

        def update(self, key, transform):
            documents[key] = transform(deepcopy(documents.get(key)))
            return documents[key]

    monkeypatch.setattr(module, 'Catalog', MemoryCatalog)
    if lost_response:
        with pytest.raises(RuntimeError):
            module.process(Remote(), config, 'fixed-source')
    else:
        assert module.process(Remote(), config, 'fixed-source')['dispatched']
    assert module.process(Remote(), config, 'fixed-source')['dispatched'] is False
    assert len(posts) == 1 and documents['jobs/' + duration['id']] == before
    assert 'jobs/' + validation_identity(config) in documents

"""Selection and dispatch contracts; no solver or fitted model is invoked."""

import base64
import hashlib
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from honeycomb_studio.cloud_matrix import prepare, validate_source
from honeycomb_studio.duration_followup import comparison_report, plan_followup
from honeycomb_studio.models import BatchSpec, ModelSpec, digest, expand


def source_data():
    spec = BatchSpec(model=ModelSpec(core_topology='reentrant_0', reentrant_geometry='angle', cpus=4,
                                    duration=.008, field_intervals=800, history_intervals=4000),
                     sampling='table', designs=[{'foil': .08 + i * .01} for i in range(6)],
                     execution_mode='parallel', max_parallel_runs=6).model_dump()
    parent = prepare({'id': 'a' * 32, 'name': 'fixture', 'profile': 'research', 'status': 'draft',
                      'spec': spec, 'input_hash': digest(spec)}, 123)
    for shard, sea in zip(parent['shards'], [900., 1100., 1400., 1000., 1050., 950.], strict=True):
        shard.update(status='review', archive_verified=True, runs=[{
            'id': 'result-' + str(shard['index']), 'status': 'review',
            'quality': {'numerical_quality': 'passed'},
            'summary': {'SEA_core_J_kg': sea, 'solver_completed': True,
                        'history_integrity_passed': True, 'damage_fields_complete': True,
                        'last_time_s': .008, 'rear_skin_deleted': shard['index'] == 2,
                        'max_rear_downward_mm': 4., 'event_finished': False}}])
    parent['status'] = 'review'
    config = {'repository': 'xuankhanh24/honeycomb-abaqus-studio', 'source_workflow_run_id': 123,
              'source_job_id': parent['id'], 'source_sha': 'old-sha', 'source_input_hash': parent['input_hash'],
              'candidate_ids': ['S1', 'S2', 'S3', 'S4', 'S5', 'B0249'],
              'physics_sha256': {'fixture.py': hashlib.sha256(b'fixture').hexdigest()}}
    run = {'id': 123, 'head_sha': 'old-sha', 'head_branch': 'main', 'status': 'completed',
           'repository': {'full_name': config['repository']}, 'path': '.github/workflows/abaqus-linux.yml',
           'html_url': 'https://github.com/fixture/source'}
    return parent, run, config


def test_select_measured_rear_intact_best_and_preserve_all_other_physics():
    parent, run, config = source_data()
    before = deepcopy(parent)
    result = plan_followup(parent, run, config, 'new-sha')
    assert parent == before
    assert result['validation_context']['candidate_ids'] == ['B0249', 'S2']
    assert result['validation_context']['selected_SEA_at_8ms_J_kg'] == 1100.
    assert result['validation_context']['models_refit'] is False
    models = expand(BatchSpec.model_validate(result['spec']))
    assert len(models) == 2
    for model in models:
        assert model['resolved']['duration'] == .012
        assert model['resolved']['duration'] / model['resolved']['field_intervals'] == pytest.approx(.008 / 800)
        assert model['resolved']['duration'] / model['resolved']['history_intervals'] == pytest.approx(.008 / 4000)
        assert model['resolved']['cpus'] == 4
    assert plan_followup(parent, run, config, 'new-sha') == result
    validate_source(result, 'new-sha')
    with pytest.raises(ValueError, match='no solver admitted'):
        validate_source(result, 'main-moved-after-dispatch')


def test_waiting_source_is_read_only_and_identity_is_checked_first():
    _, run, config = source_data()
    run['status'] = 'in_progress'
    assert plan_followup({}, run, config, 'new-sha') is None
    run['head_sha'] = 'unexpected'
    with pytest.raises(ValueError, match='identity'):
        plan_followup({}, run, config, 'new-sha')


@pytest.mark.parametrize('problem', ['unarchived', 'baseline_invalid', 'changed_input', 'no_feasible'])
def test_no_dispatch_plan_from_unusable_source_results(problem):
    parent, run, config = source_data()
    if problem == 'unarchived':
        parent['shards'][0]['archive_verified'] = False
    elif problem == 'baseline_invalid':
        parent['shards'][5]['runs'][0]['summary']['history_integrity_passed'] = False
    elif problem == 'changed_input':
        parent['shards'][0]['spec']['model']['duration'] = .012
    else:
        for shard in parent['shards'][:-1]:
            shard['runs'][0]['summary']['rear_skin_deleted'] = True
    with pytest.raises(ValueError):
        plan_followup(parent, run, config, 'new-sha')


def test_invalid_candidate_is_excluded_without_replacing_observed_data():
    parent, run, config = source_data()
    parent['shards'][1]['runs'][0]['summary']['SEA_core_J_kg'] = float('nan')
    result = plan_followup(parent, run, config, 'new-sha')
    assert result['validation_context']['candidate_ids'] == ['B0249', 'S5']


def completed_followup():
    source, run, config = source_data()
    request = plan_followup(source, run, config, 'new-sha')
    followup = prepare(request, 999)
    for shard, index in zip(followup['shards'], [5, 1], strict=True):
        original = source['shards'][index]['runs'][0]
        result = deepcopy(original)
        result['restart_state'] = {'available': True}
        result['summary'].update(last_time_s=.012, SEA_core_J_kg=original['summary']['SEA_core_J_kg'] * 1.001,
                                 max_rear_downward_mm=4.01, event_finished=True)
        shard.update(status='review', archive_verified=True, runs=[result])
    followup['status'] = 'review'
    return source, followup, run, config


def test_report_does_not_equate_small_sea_change_with_finished_event():
    source, followup, run, config = completed_followup()
    report = comparison_report(source, followup, run, config)
    assert report['physical_validation'] == 'not_established'
    assert len(report['cases']) == 2
    for row in report['cases']:
        assert abs(row['SEA_change_relative_to_12_percent']) < 2
        assert row['12ms_event_finished'] is True
        assert row['8ms_satisfies_duration_checks'] is False  # Source event was not finished.
    followup['shards'][1]['runs'][0]['summary']['event_finished'] = False
    report = comparison_report(source, followup, run, config)
    assert report['cases'][1]['12ms_event_finished'] is False


@pytest.mark.parametrize('problem', ['no_restart', 'changed_model', 'incomplete'])
def test_report_requires_original_physics_sealed_restart_and_verified_archive(problem):
    source, followup, run, config = completed_followup()
    if problem == 'no_restart':
        followup['shards'][0]['runs'][0]['restart_state']['available'] = False
    elif problem == 'changed_model':
        followup['spec']['model']['duration'] = .013
    else:
        followup['shards'][1]['archive_verified'] = False
    with pytest.raises(ValueError):
        comparison_report(source, followup, run, config)


@pytest.mark.parametrize('lost_response', [False, True])
def test_dispatch_claim_prevents_duplicate_jobs_even_after_lost_response(monkeypatch, lost_response):
    parent, run, config = source_data()
    path = Path(__file__).parents[1] / 'scripts/dispatch_duration_followup.py'
    spec = importlib.util.spec_from_file_location('dispatch_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    documents = {'jobs/' + parent['id']: parent}
    posts = []

    class Remote:
        repository = config['repository']

        def repo(self, method, route, body=None):
            if route.startswith('/actions/runs/'):
                return run
            if route == '/branches/main':
                return {'commit': {'sha': 'new-sha'}}
            if route.startswith('/contents/'):
                return {'content': base64.b64encode(b'fixture').decode()}
            assert method == 'POST' and route.endswith('/dispatches')
            posts.append(body)
            if lost_response:
                raise RuntimeError('fixture: dispatch may have been accepted')

    class MemoryCatalog:
        def __init__(self, _):
            pass

        def get(self, key):
            return deepcopy(documents.get(key)), 'fixture'

        def update(self, key, transform):
            documents[key] = transform(deepcopy(documents.get(key)))
            return deepcopy(documents[key])

    monkeypatch.setattr(module, 'Catalog', MemoryCatalog)
    if lost_response:
        with pytest.raises(RuntimeError, match='may have been accepted'):
            module.dispatch(Remote(), config, execution_sha='new-sha')
    else:
        assert module.dispatch(Remote(), config, execution_sha='new-sha')['dispatched'] is True
    second = module.dispatch(Remote(), config, execution_sha='new-sha')
    assert second['status'] == 'already_requested' and second['dispatched'] is False
    assert len(posts) == 1

"""Timeout handoff preserves successes and never dispatches a duplicate solver."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from test_cloud_matrix import batch

from honeycomb_studio.automatic_continuation import dispatch, recovery_plan
from honeycomb_studio.cloud_matrix import prepare, recover, validate_source


def fixture():
    parent = prepare(batch(), 123)
    parent['status'] = 'timed_out'
    parent['validation_context'] = {'expected_source_sha': 'a' * 40}
    parent['shards'][0].update(status='completed', archive_verified=True, workflow_run_id=123)
    for shard in parent['shards'][1:]:
        shard.update(status='timed_out', error='timed_out: budget exhausted')
    policy = dict(repository='owner/repo', source_job_id=parent['id'], source_workflow_run_id=123,
                  source_sha='a' * 40, input_hash=parent['input_hash'],
                  allow_initial_restart_without_checkpoint=True,
                  physics_sha256={'src/honeycomb_studio/models.py': 'f' * 64})
    run = dict(id=123, status='completed', conclusion='failure', head_sha='a' * 40,
               head_branch='main', repository={'full_name': 'owner/repo'},
               path='.github/workflows/abaqus-linux.yml')
    return parent, policy, run


def test_active_source_waits_without_modifying_its_catalog():
    parent, policy, run = fixture()
    run['status'] = 'in_progress'
    before = deepcopy(parent)
    assert recovery_plan(parent, run, policy)['status'] == 'waiting_for_source'
    assert parent == before


def test_timeout_plan_distinguishes_initial_recalculation_and_future_continuation():
    parent, policy, run = fixture()
    plan = recovery_plan(parent, run, policy)
    assert plan['retained_indices'] == [0]
    assert plan['initial_restart_indices'] == [1, 2]
    assert plan['postprocess_only_indices'] == []
    assert plan['status'] == 'ready'
    policy['allow_initial_restart_without_checkpoint'] = False
    with pytest.raises(ValueError, match='checkpoint'):
        recovery_plan(parent, run, policy)


@pytest.mark.parametrize('problem', ['cancel', 'different_source', 'changed_input', 'physics_failure'])
def test_handoff_refuses_cancellation_changed_inputs_and_unrelated_failures(problem):
    parent, policy, run = fixture()
    if problem == 'cancel':
        parent['cancel_requested'] = True
        assert recovery_plan(parent, run, policy)['status'] == 'cancelled'
        return
    if problem == 'different_source':
        run['head_sha'] = 'c' * 40
    elif problem == 'changed_input':
        parent['spec']['model']['foil'] *= 2
    else:
        parent['shards'][1].update(status='failed', error='negative volume')
    with pytest.raises(ValueError):
        recovery_plan(parent, run, policy)


def test_all_verified_cases_need_no_new_workflow():
    parent, policy, run = fixture()
    for shard in parent['shards']:
        shard.update(status='completed', archive_verified=True)
    assert recovery_plan(parent, run, policy)['status'] == 'already_complete'


def test_source_exception_requires_the_exact_one_time_recovery_authorization():
    parent, _, _ = fixture()
    with pytest.raises(ValueError, match='Source'):
        validate_source(parent, 'b' * 40)
    parent['automatic_continuation_execution'] = dict(source_sha='b' * 40,
        source_workflow_run_id=123, input_hash=parent['input_hash'])
    with pytest.raises(ValueError, match='Source'):
        validate_source(parent, 'b' * 40)
    parent['recovery_dispatch_pending'] = True
    validate_source(parent, 'b' * 40)
    with pytest.raises(ValueError, match='Source'):
        validate_source(parent, 'c' * 40)
    parent['workflow_run_id'] = 456
    with pytest.raises(ValueError, match='Source'):
        validate_source(parent, 'b' * 40)


def test_dispatch_is_claimed_once_and_preserves_original_context(monkeypatch):
    from honeycomb_studio import automatic_continuation as module
    parent, policy, run = fixture()
    context, successes = deepcopy(parent['validation_context']), deepcopy(parent['shards'][0])
    calls = []

    class Memory:
        def get(self, key):
            return deepcopy(parent), None

        def update(self, key, transform):
            parent.update(transform(deepcopy(parent)))
            return deepcopy(parent)

    def repo(method, path, body=None):
        if '/jobs?' in path:
            return {'jobs': []}
        if method == 'GET' and path.startswith('/actions/runs/'):
            return run
        if method == 'GET' and path == '/branches/main':
            return {'commit': {'sha': 'b' * 40}}
        calls.append((method, path, body))

    github = SimpleNamespace(repository='owner/repo', repo=repo)
    monkeypatch.setattr(module, 'Catalog', lambda github: Memory())
    monkeypatch.setattr(module, 'verify_execution_source', lambda *args: None)
    assert dispatch(github, policy, execution_sha='b' * 40)['dispatched'] is True
    assert dispatch(github, policy, execution_sha='b' * 40)['dispatched'] is False
    assert len(calls) == 1
    assert calls[0][1] == '/actions/workflows/abaqus-continuation.yml/dispatches'
    assert parent['validation_context'] == context and parent['shards'][0] == successes
    recovered = recover(parent, 456)
    assert recovered['shards'][0] == successes
    assert recovered['shards'][1]['previous_attempts'][0]['status'] == 'timed_out'


def test_hard_runner_timeout_is_identified_even_if_finalizer_makes_workflow_failure():
    parent, policy, run = fixture()
    parent['shards'][1].update(status='blocked_environment', error='Runner ended before a durable final result')
    run['timed_out_indices'] = [1]
    assert recovery_plan(parent, run, policy)['initial_restart_indices'] == [1, 2]


def test_research_web_and_automatic_handoff_use_the_verified_segment_workflow():
    from pathlib import Path
    root = Path(__file__).parents[1]
    workflow = (root / '.github/workflows/automatic-native-continuation.yml').read_text(encoding='utf-8')
    assert 'workflow_run:' in workflow and 'types: [completed]' in workflow
    assert 'actions: write' in workflow and 'cancel-in-progress: false' in workflow
    stages = (root / '.github/workflows/abaqus-continuation.yml').read_text(encoding='utf-8')
    assert all(f'  segment{i}:' in stages for i in range(4))
    assert stages.count('max_parallel: ${{ fromJSON(needs.prepare.outputs.max_parallel) }}') == 4


def test_execution_handoff_checks_every_original_physical_module():
    import base64
    import hashlib

    from honeycomb_studio.automatic_continuation import verify_execution_source
    from honeycomb_studio.solver_checkpoint import PHYSICS
    body = b'original scientific module fixture'
    hashes = {'src/honeycomb_studio/' + path: hashlib.sha256(body).hexdigest() for path in PHYSICS}
    calls = []
    def repo(method, path):
        calls.append(path)
        return ({'commit': {'sha': 'b' * 40}} if path == '/branches/main'
                else {'content': base64.b64encode(body).decode()})
    policy = {'physics_sha256': hashes}
    verify_execution_source(SimpleNamespace(repo=repo), policy, 'b' * 40)
    assert len(calls) == 7
    hashes[next(iter(hashes))] = '0' * 64
    with pytest.raises(ValueError, match='source changed'):
        verify_execution_source(SimpleNamespace(repo=repo), policy, 'b' * 40)

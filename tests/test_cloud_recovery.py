import base64
import json

import httpx
from test_cloud_matrix import batch

from honeycomb_studio.cloud_github import Catalog, Github
from honeycomb_studio.cloud_matrix import prepare, recover


def test_catalog_recovers_500_and_rereads_sibling_changes(monkeypatch):
    monkeypatch.setattr('honeycomb_studio.cloud_github.time.sleep', lambda _: None)
    state = {'value': {'count': 0, 'sibling': 0}, 'writes': 0}

    def handler(request):
        if '/git/ref/' in request.url.path:
            return httpx.Response(200, json={'object': {'sha': 'main'}})
        if request.method == 'GET':
            return httpx.Response(200, json={'content': base64.b64encode(json.dumps(state['value']).encode()).decode(), 'sha': str(state['writes'])})
        state['writes'] += 1
        if state['writes'] == 1:
            state['value']['sibling'] = 5
            return httpx.Response(500, json={'message': 'temporary'})
        state['value'] = json.loads(base64.b64decode(json.loads(request.content)['content']))
        return httpx.Response(200, json={})

    catalog = Catalog(Github(token='fixture', client=httpx.Client(transport=httpx.MockTransport(handler))))
    assert catalog.update('fixture', lambda old: {**old, 'count': old['count'] + 1}) == {'count': 1, 'sibling': 5}


def test_catalog_lost_response_does_not_apply_transform_twice(monkeypatch):
    monkeypatch.setattr('honeycomb_studio.cloud_github.time.sleep', lambda _: None)
    state = {'value': {'count': 0}}

    def handler(request):
        if '/git/ref/' in request.url.path:
            return httpx.Response(200, json={'object': {'sha': 'main'}})
        if request.method == 'GET':
            return httpx.Response(200, json={'content': base64.b64encode(json.dumps(state['value']).encode()).decode(), 'sha': 'sha'})
        state['value'] = json.loads(base64.b64decode(json.loads(request.content)['content']))
        raise httpx.ReadError('response lost', request=request)

    catalog = Catalog(Github(token='fixture', client=httpx.Client(transport=httpx.MockTransport(handler))))
    assert catalog.update('fixture', lambda old: {'count': old['count'] + 1}) == {'count': 1}


def test_recovery_keeps_successes_and_original_workflow_provenance():
    parent = prepare(batch(), 123)
    parent['status'] = 'failed'
    parent['shards'][0].update(status='completed', archive_verified=True, workflow_run_id=123, runs=[{'id': 'saved'}])
    parent['shards'][1].update(status='review', archive_verified=True, workflow_run_id=123)
    parent['shards'][2].update(status='failed', archive_verified=True, workflow_run_id=123, error='500', runs=[])
    recovered = recover(parent, 456)
    assert recovered['shards'][:2] == parent['shards'][:2]
    retry = recovered['shards'][2]
    assert retry['status'] == 'draft' and 'workflow_run_id' not in retry
    assert retry['previous_attempts'][0]['workflow_run_id'] == 123
    assert retry['id'] != parent['shards'][2]['id']
    assert retry['previous_attempts'][0]['id'] == parent['shards'][2]['id']
    assert retry['spec'] == parent['shards'][2]['spec']
    assert recovered['workflow_run_id'] == 456
    assert parent['status'] == 'failed'

def test_recovery_rejects_active_duplicate_or_successful_job():
    import pytest

    parent = prepare(batch(), 123)
    with pytest.raises(ValueError, match='terminal'):
        recover(parent, 456)
    for shard in parent['shards']:
        shard.update(status='completed', archive_verified=True)
    parent['status'] = 'completed'
    with pytest.raises(ValueError, match='No failed'):
        recover(parent, 456)


def test_owner_can_dispatch_one_selective_recovery_but_not_duplicate(monkeypatch):
    from fastapi.testclient import TestClient
    from itsdangerous import TimestampSigner
    from test_cloud_matrix import MemoryCatalog

    from honeycomb_studio import cloud_api

    parent = prepare(batch(), 123)
    parent['status'] = 'failed'
    for shard in parent['shards'][:2]:
        shard.update(status='completed', archive_verified=True, workflow_run_id=123)
    parent['shards'][2].update(status='failed', workflow_run_id=123)
    memory = MemoryCatalog(parent)
    calls = []
    class Connected:
        configured = True

        def repo(self, method, path, body=None):
            if method == 'GET':
                return {'status': 'completed'}
            calls.append((path, body))

    monkeypatch.setattr(cloud_api, 'Catalog', lambda github: memory)
    monkeypatch.setattr(cloud_api, 'gates', lambda: [])
    monkeypatch.setenv('WEB_SESSION_SECRET', 'recovery-test-only')
    monkeypatch.setenv('WEB_LOCAL_HTTP', '1')
    with TestClient(cloud_api.create_app(Connected())) as client:
        path = '/api/jobs/' + parent['id'] + '/recover'
        assert client.post(path, json={}).status_code == 403
        session = base64.b64encode(json.dumps({'user_id': cloud_api.OWNER_ID, 'csrf': 'fixture'}).encode())
        client.cookies.set('session', TimestampSigner('recovery-test-only').sign(session).decode())
        headers = {'X-Honeycomb-CSRF': 'fixture'}
        assert client.post(path, json={}, headers=headers).status_code == 200
        assert client.post(path, json={}, headers=headers).status_code == 409
    assert len(calls) == 1 and calls[0][1]['inputs']['recover'] is True
    assert memory.parent['shards'] == parent['shards']


def test_get_retries_transient_failure_but_post_does_not(monkeypatch):
    import pytest

    monkeypatch.setattr('honeycomb_studio.cloud_github.time.sleep', lambda _: None)
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(500 if len(calls) == 1 else 200, json={'ok': True})

    github = Github(token='fixture', client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert github.repo('GET', '/fixture') == {'ok': True}
    assert calls == ['GET', 'GET']
    calls.clear()
    with pytest.raises(httpx.HTTPStatusError):
        github.repo('POST', '/actions/workflows/fixture/dispatches')
    assert calls == ['POST']


def test_collection_uses_each_shards_original_workflow(tmp_path, monkeypatch):
    import hashlib
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location('collection_recovery', Path(__file__).parents[1] / 'scripts/collect_cloud_training.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = json.dumps({'complete': False, 'files': []}).encode()
    parent = {'id': 'a' * 32, 'name': 'recovery', 'status': 'failed', 'profile': 'research', 'workflow_run_id': 456,
              'shards': [{'id': char * 32, 'index': i, 'status': 'failed', 'archive_verified': True,
                          'release_url': 'fixture', 'workflow_run_id': workflow}
                         for i, (char, workflow) in enumerate([('b', 123), ('c', 456)])]}
    class CatalogFixture:
        def jobs(self):
            return [{'id': parent['id']}]

        def get(self, key):
            return parent, None

    def repo(method, path):
        if '/tags/' in path:
            return {'id': 1 if path.endswith('b' * 32) else 2, 'html_url': 'fixture'}
        workflow = 123 if '/releases/1/' in path else 456
        return [{'name': f'workflow-{workflow}-artifact-manifest.json', 'size': len(manifest),
                 'digest': 'sha256:' + hashlib.sha256(manifest).hexdigest(), 'browser_download_url': 'fixture'}]

    monkeypatch.setattr(module, 'public_asset', lambda url: url)
    monkeypatch.setattr(module, 'validate_manifest', lambda *a, **kw: None)
    github = SimpleNamespace(repo=repo, client=SimpleNamespace(get=lambda url: SimpleNamespace(
        raise_for_status=lambda: None, content=manifest)))
    sources = module.collect(github, CatalogFixture(), tmp_path)
    assert [source['workflow_run_id'] for source in sources] == [123, 456]


def test_recovery_prefers_verified_solver_and_retains_it_across_failed_extractions():
    from honeycomb_studio.cloud_github import REPOSITORY
    from honeycomb_studio.solver_checkpoint import KIND

    parent = prepare(batch(), 123)
    parent['status'] = 'failed'
    for shard in parent['shards'][:2]:
        shard.update(status='completed', archive_verified=True)
    original = parent['shards'][2]
    reference = {'kind': KIND, 'available': True, 'input_hash': original['input_hash'],
                 'run_input_hash': 'a' * 64, 'runtime_hash': 'c' * 64, 'source_sha': 'd' * 40,
                 'manifest': {'asset_id': 123, 'bytes': 100, 'digest': 'sha256:' + 'e' * 64,
                              'url': f'https://github.com/{REPOSITORY}/releases/download/fixture/manifest.json'}}
    original.update(status='failed', solver_checkpoint=reference)
    recovered = recover(parent, 456)
    assert recovered['shards'][:2] == parent['shards'][:2]
    assert recovered['shards'][2]['postprocess_source'] == reference
    recovered['status'] = 'failed'
    recovered['shards'][2]['status'] = 'failed'
    again = recover(recovered, 789)
    assert again['shards'][2]['postprocess_source'] == reference
    assert len(again['shards'][2]['previous_attempts']) == 2
    original['solver_checkpoint']['input_hash'] = '0' * 64
    import pytest

    with pytest.raises(ValueError, match='checkpoint identity'):
        recover(parent, 456)


def test_packaged_web_can_choose_postprocessing_without_loading_the_native_engine():
    import subprocess
    import sys
    from pathlib import Path

    from honeycomb_studio.cloud_github import REPOSITORY
    from honeycomb_studio.solver_checkpoint_ref import KIND

    parent = prepare(batch(), 123)
    parent['status'] = 'failed'
    for shard in parent['shards'][:2]:
        shard.update(status='completed', archive_verified=True)
    shard = parent['shards'][2]
    shard.update(status='failed', solver_checkpoint={
        'kind': KIND, 'available': True, 'input_hash': shard['input_hash'],
        'run_input_hash': 'a' * 64, 'runtime_hash': 'c' * 64, 'source_sha': 'd' * 40,
        'manifest': {'asset_id': 123, 'bytes': 100, 'digest': 'sha256:' + 'e' * 64,
                     'url': f'https://github.com/{REPOSITORY}/releases/download/fixture/manifest.json'},
    })
    program = """
import json, sys
sys.path.insert(0, sys.argv[1])
from service.cloud_matrix import recover
result = recover(json.load(sys.stdin), 456)
assert result['shards'][2]['postprocess_source']['available'] is True
assert 'service.solver_checkpoint' not in sys.modules
assert 'honeycomb_studio.engine' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, '-B', '-I', '-c', program, str(Path(__file__).parents[1] / 'web')],
        input=json.dumps(parent), text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_empty_recorded_checkpoint_cannot_silently_start_a_new_solver():
    import pytest

    for bad in (None, {}, False):
        parent = prepare(batch(), 123)
        parent['status'] = 'failed'
        for shard in parent['shards'][:2]:
            shard.update(status='completed', archive_verified=True)
        parent['shards'][2].update(status='failed', solver_checkpoint=bad)
        with pytest.raises(ValueError, match='checkpoint identity'):
            recover(parent, 456)

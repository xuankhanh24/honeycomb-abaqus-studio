"""Closed-state transport tests; fixtures do not represent a native solve."""

import hashlib
import json

import httpx
import pytest

from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_github import REPOSITORY
from honeycomb_studio.cloud_publication import prepare
from honeycomb_studio.cloud_restore import restore
from honeycomb_studio.completed_restart import completed_restart_records, seal_completed_restart


def completed_run(root):
    attempt = root / 'runs/r1/attempts/001'
    raw = attempt / 'raw'
    raw.mkdir(parents=True)
    for extension in ('abq.1', 'abq.2', 'mdl', 'pac', 'stt', 'prt', 'res', 'sel', 'odb'):
        (raw / ('job.' + extension)).write_bytes(('transport fixture: ' + extension).encode())
    (raw / 'job.abq').write_bytes(b'')  # Preserve an empty master stub beside nonempty domain state.
    (raw / 'other.abq').write_bytes(b'unrelated job')
    (raw / 'job.private').write_bytes(b'not a native restart family')
    (attempt / 'solver-complete.json').write_text(json.dumps({
        'sta': {'solver_success': True, 'simulation_time_s': .008}}))
    return {'id': 'r1', 'input_hash': 'input', 'status': 'review',
            'summary': {'solver_completed': True},
            'resolved': {'duration': .008, 'cpus': 4, 'precision': 'double'},
            'attempts': [{'path': str(attempt), 'job_name': 'job', 'process': None}]}


def test_complete_native_families_round_trip_without_copying_large_state(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    run = completed_run(source)
    sealed = seal_completed_restart(source, run, {'release': 'fixture'})
    assert sealed['available'] is True and sealed['files'] == 10
    raw = source / 'runs/r1/attempts/001/raw'
    view = tmp_path / 'publication'
    view.mkdir()
    prepare(source, view)
    assert (view / 'runs/r1/attempts/001/raw/job.abq.2').samefile(raw / 'job.abq.2')
    assert not (view / 'runs/r1/attempts/001/raw/other.abq').exists()
    assert not (view / 'runs/r1/attempts/001/raw/job.private').exists()
    payloads = {}

    def upload(self, path, name):
        url = f'https://github.com/{REPOSITORY}/releases/download/fixture/{name}'
        data = path.read_bytes()
        payloads[url] = data
        return {'url': url, 'bytes': len(data), 'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}

    monkeypatch.setattr(ReleaseArchive, 'upload', upload)
    manifest = ReleaseArchive(None, 1, limit=41).publish(source, attempt='fixture', complete=True)
    target = tmp_path / 'restored'
    with httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=payloads[str(request.url)]))) as client:
        restore(manifest, target, client=client)
    original = completed_restart_records(source)
    assert completed_restart_records(target) == original
    for name in original:
        assert (target / name).read_bytes() == (source / name).read_bytes()


@pytest.mark.parametrize('problem', ['live', 'unfinished', 'missing', 'wrong_time', 'synthetic'])
def test_do_not_certify_an_unusable_end_state(tmp_path, problem):
    run = completed_run(tmp_path)
    folder = tmp_path / 'runs/r1/attempts/001'
    if problem == 'live':
        run['attempts'][0]['process'] = {'pid': 123}
    elif problem == 'unfinished':
        run['status'] = 'solving'
    elif problem == 'missing':
        (folder / 'raw/job.sel').unlink()
    elif problem == 'synthetic':
        run['test_only'] = True
    else:
        (folder / 'solver-complete.json').write_text(json.dumps({
            'sta': {'solver_success': True, 'simulation_time_s': .007}}))
    with pytest.raises(ValueError):
        seal_completed_restart(tmp_path, run, {})
    assert not (folder / 'restart-state.json').exists()


def test_tampered_native_state_prevents_complete_manifest(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    run = completed_run(source)
    seal_completed_restart(source, run, {})
    (source / 'runs/r1/attempts/001/raw/job.abq.2').write_bytes(b'changed after sealing')
    uploads = []

    def upload(self, path, name):
        uploads.append(name)
        data = path.read_bytes()
        return {'url': 'https://github.com/fixture/' + name, 'bytes': len(data),
                'digest': 'sha256:' + hashlib.sha256(data).hexdigest()}

    monkeypatch.setattr(ReleaseArchive, 'upload', upload)
    with pytest.raises(ValueError, match='changed after sealing'):
        ReleaseArchive(None, 1).publish(source, attempt='fixture', complete=True)
    assert not any(name.endswith('artifact-manifest.json') for name in uploads)


def test_receipt_cannot_admit_unrelated_or_private_paths(tmp_path):
    run = completed_run(tmp_path)
    seal_completed_restart(tmp_path, run, {})
    path = tmp_path / 'runs/r1/attempts/001/restart-state.json'
    receipt = json.loads(path.read_text())
    receipt['files']['../../credentials/oauth.json'] = {'bytes': 1, 'sha256': '0' * 64}
    path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='Unsafe native restart inventory'):
        completed_restart_records(tmp_path)

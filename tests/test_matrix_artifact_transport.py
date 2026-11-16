"""Transport fixtures never establish Abaqus or physical validation."""

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from honeycomb_studio.models import BatchSpec, ModelSpec, digest, expand
from honeycomb_studio.solver_checkpoint import physics_hashes
from honeycomb_studio.store import Store, write_json


@pytest.fixture
def transport(monkeypatch):
    scripts = Path(__file__).parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('matrix_transport_fixture', scripts / 'recover_matrix_artifact.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_subset_keeps_native_bytes_and_excludes_interrupted_exports(tmp_path, transport):
    blob = tmp_path / 'original.zip'
    with zipfile.ZipFile(blob, 'w') as archive:
        archive.writestr('cloud-request.json', '{}')
        archive.writestr('projects/p/runs/r/raw/native.odb', b'original ODB fixture')
        archive.writestr('projects/p/runs/r/extracted/summary.json', '{"not_complete":true}')
        archive.writestr('credentials/private.json', 'private fixture')
    transport.extract_subset(blob, tmp_path / 'restored')
    assert (tmp_path / 'restored/projects/p/runs/r/raw/native.odb').read_bytes() == b'original ODB fixture'
    assert not (tmp_path / 'restored/projects/p/runs/r/extracted').exists()
    assert not (tmp_path / 'restored/credentials').exists()


@pytest.mark.parametrize('member', ['../escape.json', '/absolute.json', 'C:/drive.json', 'raw/native.lck'])
def test_bad_or_locked_member_is_rejected_before_exposing_files(tmp_path, transport, member):
    blob = tmp_path / 'bad.zip'
    with zipfile.ZipFile(blob, 'w') as archive:
        archive.writestr(member, 'fixture')
    with pytest.raises(ValueError, match='(Unsafe|locked)'):
        transport.extract_subset(blob, tmp_path / 'rejected')
    assert not (tmp_path / 'rejected').exists()


@pytest.mark.parametrize('problem', [None, 'wrong_inputs', 'wrong_physics', 'unfinished_STA'])
def test_original_admission_checks_solver_and_science(tmp_path, transport, problem):
    root = tmp_path / 'original'
    store = Store(root)
    spec = BatchSpec(model=ModelSpec(duration=0.008, velocity_m_s=6.5, cpus=4))
    batch = store.create(spec)
    native = store.list('runs', batch['id'])[0]
    attempt = Path(native['path']) / 'attempts/001'
    (attempt / 'raw').mkdir(parents=True)
    (attempt / 'raw/native.odb').write_bytes(b'closed ODB fixture')
    (attempt / 'raw/native.inp').write_text('original input fixture')
    (attempt / 'raw/native.sta').write_text(
        ' 100 8.000E-03 8.000E-03 00:01:00 1E-07 1 1.0 2.0\n'
        + ('THE ANALYSIS HAS NOT BEEN COMPLETED\n' if problem == 'unfinished_STA'
           else 'THE ANALYSIS HAS COMPLETED SUCCESSFULLY\n'))
    write_json(attempt / 'solver-complete.json', {'sta': {'solver_success': True}})
    science = physics_hashes()
    if problem == 'wrong_physics':
        science['models.py'] = 'changed'
    native['attempts'] = [{'number': 1, 'path': str(attempt), 'job_name': 'native',
                           'process': None, 'software': {'source_sha256': science}}]
    if problem == 'wrong_inputs':
        native['resolved']['duration'] = 0.012
    write_json(Path(native['path']) / 'run.json', native)
    write_json(root / 'runtime-lock.json', {'release': 'fixture-only'})
    write_json(root / 'cloud-request.json', {'input_hash': digest(spec.model_dump()), 'spec': spec.model_dump()})
    shard = {'input_hash': digest(spec.model_dump()), 'spec': spec.model_dump()}
    if problem:
        with pytest.raises(ValueError):
            transport.verify_original(root, shard)
    else:
        result = transport.verify_original(root, shard)
        assert result['STA']['solver_success'] is True
        assert json.loads((Path(native['path']) / 'run.json').read_text(encoding='utf-8')) == native
        assert native['input_hash'] == expand(spec)[0]['input_hash']

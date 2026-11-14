"""Seal closed Explicit end states for later restart on another runner."""

import hashlib
import json
import math
import re
from pathlib import Path

from .models import digest
from .store import write_json

FAMILIES = ('abq', 'mdl', 'pac', 'stt', 'prt', 'res', 'sel', 'odb')
KIND = 'honeycomb-completed-explicit-restart'


def _family(name, job_name):
    match = re.fullmatch(re.escape(job_name) + r'\.(' + '|'.join(FAMILIES) + r')(?:\.\d+)*', name)
    return match[1] if match else None


def _inventory(raw, job_name):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,127}', job_name):
        raise ValueError('Invalid native restart job name')
    files = {}
    for path in sorted(raw.iterdir()):
        if not _family(path.name, job_name):
            continue
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError('Invalid native restart file: ' + path.name)
        with path.open('rb') as stream:
            files[path.name] = {'bytes': path.stat().st_size,
                                'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    missing = [family for family in FAMILIES if not any(_family(name, job_name) == family for name in files)]
    if missing:
        raise ValueError('Missing completed Explicit restart families: ' + ', '.join(missing))
    return files


def seal_completed_restart(root: Path, run: dict, runtime: dict):
    """Call after the solver and postprocessors have closed every attempt file."""
    if (run.get('status') not in ('completed', 'review') or
            run.get('summary', {}).get('solver_completed') is not True or not run.get('attempts')):
        raise ValueError('Cannot seal an unfinished solver attempt')
    attempt = run['attempts'][-1]
    folder = Path(attempt['path'])
    folder.resolve().relative_to(root.resolve())
    raw = folder / 'raw'
    if folder.is_symlink() or raw.is_symlink() or attempt.get('process'):
        raise ValueError('Cannot seal live or linked solver output')
    complete = json.loads((folder / 'solver-complete.json').read_text(encoding='utf-8'))
    target = run['resolved']['duration']
    sta = complete.get('sta', {})
    if sta.get('solver_success') is not True or not math.isclose(
            sta.get('simulation_time_s', -1), target, rel_tol=1.e-6, abs_tol=1.e-9):
        raise ValueError('Missing successful solver end-state evidence')
    if (raw / (attempt['job_name'] + '.lck')).exists():
        raise ValueError('Native restart output is still locked')
    receipt = {'schema_version': '1', 'kind': KIND, 'complete': True,
               'run_id': run['id'], 'job_name': attempt['job_name'], 'input_hash': run['input_hash'],
               'runtime': runtime, 'runtime_hash': digest(runtime),
               'cpus': run['resolved']['cpus'], 'precision': run['resolved']['precision'],
               'step': 1, 'step_end': True, 'simulation_time_s': target,
               'software': attempt.get('software', {}), 'files': _inventory(raw, attempt['job_name'])}
    write_json(folder / 'restart-state.json', receipt)
    return {'available': True, 'receipt_path': (folder / 'restart-state.json').relative_to(root).as_posix(),
            'simulation_time_s': target, 'files': len(receipt['files']),
            'runtime_hash': receipt['runtime_hash'], 'input_hash': run['input_hash']}


def completed_restart_records(root: Path):
    """Admit only inventoried job files, including numbered domain-state files."""
    records = {}
    root = root.resolve()
    for receipt_path in sorted(root.rglob('restart-state.json')):
        if (receipt_path.is_symlink() or receipt_path.parent.parent.name != 'attempts' or
                not receipt_path.parent.name.isdecimal() or
                any(p in ('credentials', 'cache', 'spool', '.git') for p in receipt_path.relative_to(root).parts)):
            raise ValueError('Unsafe completed restart receipt location')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('kind') != KIND or receipt.get('complete') is not True:
            raise ValueError('Incomplete native restart receipt')
        job_name = receipt.get('job_name', '')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,127}', job_name):
            raise ValueError('Invalid native restart receipt identity')
        files = receipt.get('files')
        if not isinstance(files, dict) or not files:
            raise ValueError('Missing native restart inventory')
        for family in FAMILIES:
            if not any(_family(name, job_name) == family for name in files):
                raise ValueError('Incomplete native restart family: ' + family)
        for name, expected in files.items():
            if (not _family(name, job_name) or type(expected.get('bytes')) is not int or
                    expected['bytes'] <= 0 or not re.fullmatch(r'[0-9a-f]{64}', expected.get('sha256', ''))):
                raise ValueError('Unsafe native restart inventory entry')
            source = receipt_path.parent / 'raw' / name
            source.resolve().relative_to(root)
            if source.is_symlink() or source.parent.is_symlink() or not source.is_file():
                raise ValueError('Missing native restart file: ' + name)
            records[source.relative_to(root).as_posix()] = expected
    return records

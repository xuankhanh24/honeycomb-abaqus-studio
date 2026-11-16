"""Transport one pinned interrupted matrix artifact into an ODB-only archive.

No Abaqus installation or solver is involved. Numerical exports stay incomplete
until a separate SavedSolverEngine worker successfully reopens the original ODB.
"""

import argparse
import json
import os
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

import httpx
from campaign_artifact_transfer import transfer

from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_github import JOB_ID, Catalog, Github
from honeycomb_studio.models import BatchSpec, digest, expand
from honeycomb_studio.solver_checkpoint import _closed_solver, physics_hashes
from honeycomb_studio.store import write_json


def extract_subset(blob, target):
    """Read only original metadata and closed solver files after ZIP hash passes."""
    with zipfile.ZipFile(blob) as archive:
        selected = []
        for info in archive.infolist():
            relative = PurePosixPath(info.filename)
            if (relative.is_absolute() or '..' in relative.parts or '\\' in info.filename
                    or ':' in info.filename or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError('Unsafe retained artifact member')
            if info.filename.endswith('.lck'):
                raise ValueError('Retained artifact contains a locked native solver')
            if info.is_dir():
                continue
            if (info.filename in ('cloud-request.json', 'runtime-lock.json')
                    or info.filename.endswith(('/run.json', '/batch.json', '/solver-complete.json'))
                    or ('/raw/' in info.filename and info.filename.endswith(('.odb', '.sta', '.inp', '/model_manifest.json')))):
                selected.append(info)
        if shutil.disk_usage(target.parent).free < sum(i.file_size for i in selected) + 10 * 10**9:
            raise RuntimeError('Insufficient space for original solver files and reserve')
        target.mkdir()
        for info in selected:
            path = target.joinpath(*PurePosixPath(info.filename).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, path.open('xb') as destination:
                shutil.copyfileobj(source, destination, 1024 * 1024)


def verify_original(root, shard):
    """Reject wrong inputs, physics, attempts and incomplete solver evidence."""
    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))
    runs, batches = list(root.rglob('run.json')), list(root.rglob('batch.json'))
    if len(runs) != 1 or len(batches) != 1:
        raise ValueError('Expected exactly one original run and batch')
    native = read(runs[0])
    request = read(root / 'cloud-request.json')
    expected = expand(BatchSpec.model_validate(shard['spec']))[0]
    if (request.get('input_hash') != shard['input_hash']
            or digest(request.get('spec')) != shard['input_hash']
            or any(native.get(k) != expected[k] for k in ('input_hash', 'requested', 'resolved'))
            or len(native.get('attempts', [])) != 1):
        raise ValueError('Retained solver scientific inputs or original attempt differ')
    attempt = native['attempts'][0]
    if any(attempt.get('software', {}).get('source_sha256', {}).get(k) != v
           for k, v in physics_hashes().items()):
        raise ValueError('Retained solver physics differs from the processor')
    relative = runs[0].parent.relative_to(root) / 'attempts' / f"{attempt['number']:03d}"
    sta = _closed_solver(native, root / relative)
    if not (root / relative / 'raw' / (attempt['job_name'] + '.inp')).is_file():
        raise ValueError('Missing original input deck')
    return {'original_run_id': native['id'], 'original_attempt': attempt['number'],
            'STA': sta, 'runtime_hash': digest(read(root / 'runtime-lock.json')),
            'physics_sha256': physics_hashes()}


def recover(args, github):
    original = github.repo('GET', f'/actions/runs/{args.source_run_id}')
    if (original['status'] != 'completed' or original['head_branch'] != 'main'
            or original['path'] != '.github/workflows/abaqus-linux.yml'):
        raise ValueError('Expected a terminal original matrix workflow on main')
    parent, _ = Catalog(github).get('jobs/' + args.parent_job_id)
    if parent is None or parent['workflow_run_id'] != args.source_run_id:
        raise ValueError('Original workflow does not own this matrix')
    shard = next(row for row in parent['shards'] if row['index'] == args.index)
    if shard['status'] in ('completed', 'review'):
        raise ValueError('Completed sibling results must not be republished as interrupted')
    artifact = github.repo('GET', f'/actions/artifacts/{args.artifact_id}')
    if (artifact['name'] != f'recoverable-results-{args.source_run_id}-{args.index}'
            or artifact['digest'] != 'sha256:' + args.sha256 or artifact['expired']
            or not 0 < artifact['size_in_bytes'] <= 50 * 10**9):
        raise ValueError('Pinned fallback artifact identity differs')
    release = github.repo('GET', f"/releases/{shard['release_id']}")
    if release['tag_name'] != 'simulation-' + shard['id'] or release['draft']:
        raise ValueError('Original release identity differs')

    def signed_url():
        response = github.client.get(
            f'https://api.github.com/repos/{github.repository}/actions/artifacts/{args.artifact_id}/zip',
            headers={'Authorization': 'Bearer ' + github.access_token()}, follow_redirects=False)
        if response.status_code >= 400:
            response.raise_for_status()
        if response.status_code != 302 or not response.headers.get('location', '').startswith('https://'):
            raise ValueError('Artifact download authorization failed')
        return response.headers['location']

    scratch_root = Path(os.environ.get('RUNNER_TEMP', tempfile.gettempdir()))
    with tempfile.TemporaryDirectory(prefix='retained-matrix-', dir=scratch_root) as temporary:
        scratch = Path(temporary)
        if shutil.disk_usage(scratch).free < artifact['size_in_bytes'] + 10 * 10**9:
            raise RuntimeError('Insufficient transfer space')
        blob = scratch / 'immutable.zip'
        with httpx.Client(timeout=httpx.Timeout(90, connect=30), follow_redirects=True) as transport:
            transfer(transport, signed_url, artifact['size_in_bytes'], artifact['digest'], blob)
        root = scratch / 'original'
        extract_subset(blob, root)
        evidence = verify_original(root, shard)
        proof = {'kind': 'verified-retained-matrix-solver-transport-v1',
                 'source_workflow_run_id': args.source_run_id, 'source_sha': original['head_sha'],
                 'artifact_id': args.artifact_id, 'artifact_sha256': args.sha256,
                 'whole_artifact_sha256_verified': True, 'new_FE_solve': False,
                 'numerical_export_complete': False, **evidence}
        write_json(root / 'artifact-retrieval.json', proof)
        manifest = ReleaseArchive(github, release['id']).publish(
            root, attempt=f'workflow-{args.source_run_id}', complete=False,
            checkpoint=f'actions-{args.artifact_id}')
        proof['published_files'] = len(manifest['files'])
        proof['release_url'] = release['html_url']
        Path('output').mkdir(exist_ok=True)
        write_json(Path('output/retained-matrix-receipt.json'), proof)
        print(json.dumps(proof), flush=True)
        return proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run-id', type=int, required=True)
    parser.add_argument('--parent-job-id', required=True)
    parser.add_argument('--index', type=int, required=True)
    parser.add_argument('--artifact-id', type=int, required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    if (not JOB_ID.fullmatch(args.parent_job_id) or not 0 <= args.index < 100
            or len(args.sha256) != 64 or any(c not in '0123456789abcdef' for c in args.sha256)):
        parser.error('Invalid pinned matrix identity or SHA-256')
    recover(args, Github(token=os.environ['GITHUB_TOKEN']))

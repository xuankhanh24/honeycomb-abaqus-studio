"""One bounded segment of a real Explicit analysis, preserving state between runners."""
import argparse
import json
import os
import signal
import time
from pathlib import Path

from cloud_worker import require_qualification, validation_metrics_requested
from native_cloud_worker import native_runtime

from honeycomb_studio import solver
from honeycomb_studio.cloud_archive import ReleaseArchive
from honeycomb_studio.cloud_continuation import (
    checkpoint_inventory,
    verify_checkpoint,
    verify_checkpoint_history,
)
from honeycomb_studio.cloud_github import JOB_ID, Catalog, Github
from honeycomb_studio.cloud_matrix import ShardCatalog
from honeycomb_studio.cloud_progress import Progress
from honeycomb_studio.data import checksum
from honeycomb_studio.engine import Engine
from honeycomb_studio.models import BatchSpec, digest, expand
from honeycomb_studio.solver_checkpoint import (
    SavedSolverEngine,
    publish_solver_checkpoint,
    restore_solver_checkpoint,
)
from honeycomb_studio.store import Store, now, write_json


def execute_segment(root, store, run, batch, progress, runtime_hash, control, *,
                    job=None, postprocess_only=False, solver_sink=None):
    history_check = None
    with native_runtime(root, continuation=not postprocess_only) as executable:
        engine_type = SavedSolverEngine if postprocess_only else Engine
        engine = engine_type(store, abaqus=str(executable), fake=False)
        engine.explicit_continuation = not postprocess_only
        engine.continuation_control = None if postprocess_only else control
        engine.runtime_fingerprint = runtime_hash
        engine.research_archive = (job or {}).get('profile') == 'research'
        engine.validation_metrics = (validation_metrics_requested(job, postprocess_only=postprocess_only)
                                     if job else False)
        engine.solver_sink = solver_sink
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: progress.stop_solver('cancelled'))
        progress.start(os.environ['GITHUB_SHA'])
        try:
            engine.execute_wave([run], batch)
        finally:
            progress.done.set()
            progress.thread.join(timeout=70)
        run = store.get('runs', run['id'])
        if run['status'] == 'interrupted' and progress.stop_reason == 'timed_out':
            attempt = run['attempts'][-1]
            raw = Path(attempt['path']) / 'raw'
            sta = solver.sta_progress(raw / (attempt['job_name'] + '.sta'), run['resolved']['duration'])
            if sta.get('solver_success'):
                # Extraction can consume the remainder of a segment after FE completion.
                # The next segment must reuse this closed attempt and forbid FE phases.
                if (raw / (attempt['job_name'] + '.lck')).exists():
                    raise ValueError('Successful solver still has a live ODB lock')
                marker = Path(attempt['path']) / 'solver-complete.json'
                if not marker.exists():
                    write_json(marker, {'completed_at': now(), 'sta': sta})
                history_check = {'solver_completed': True, 'postprocess_only': True}
            else:
                if postprocess_only:
                    raise ValueError('Completed-solver recovery lost its successful original STA')
                # The query needs the private license config and container network.
                history_check = verify_checkpoint_history(raw, attempt['job_name'], str(executable), run['resolved'])
    return run, history_check


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-id', required=True)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--segment', type=int, required=True, choices=range(4))
    args = parser.parse_args()
    if not all(JOB_ID.fullmatch(i) for i in (args.parent_id, args.job_id)):
        raise ValueError('Invalid job identity')
    root = Path('/tmp/honeycomb-results')  # portable absolute path across all segment runners
    workflow = int(os.environ['GITHUB_RUN_ID'])
    github = Github(token=os.environ['GITHUB_TOKEN'])
    catalog = ShardCatalog(Catalog(github), args.parent_id, args.job_id, workflow)
    key = 'jobs/' + args.job_id
    job, _ = catalog.get(key)
    if job.get('cancel_requested'):
        raise ValueError('Batch cancelled')
    if args.segment == 0 and job['status'] != 'draft':
        raise ValueError('Initial segment already claimed; do not rerun duplicate jobs')
    if args.segment > 0 and job['status'] != 'running':
        raise ValueError('Continuation requires an unfinished running shard')
    if digest(job['spec']) != job['input_hash']:
        raise ValueError('Catalog input digest mismatch')
    runtime = require_qualification(Path.cwd())
    runtime_hash = digest(runtime)
    control = Path('scripts/linux_media/continuation_control.c').resolve()
    evidence = json.loads(Path('docs/evidence/orderly-explicit-checkpoint.json').read_text())
    if (not evidence.get('passed') or not evidence.get('history_integrity', {}).get('passed')
            or evidence.get('source_sha256') != checksum(control)):
        raise ValueError('Orderly checkpoint callback has not passed native history recovery acceptance')
    model = dict(job['spec'])
    # Match cloud_worker normalization exactly so a legacy closed ODB can be
    # restored without changing its scientific batch or presentation settings.
    model.update(backup_after_run=False, max_runs=20, export_all_fields=job['profile'] == 'full')
    spec = BatchSpec.model_validate(model)
    expected = expand(spec)[0]
    store = Store(root)
    marker = root / 'continuation.json'
    postprocess_only = 'postprocess_source' in job
    if args.segment == 0:
        if store.list('batches'):
            raise ValueError('Initial segment requires clean storage')
        batch = (restore_solver_checkpoint(store, job, spec, runtime, github)
                 if postprocess_only else store.create(spec))
        run = store.list('runs', batch['id'])[0]
    else:
        receipt = json.loads(marker.read_text())
        if receipt['segment'] != args.segment - 1 or receipt['child_id'] != args.job_id or receipt['workflow'] != workflow:
            raise ValueError('Wrong predecessor segment')
        batch = store.get('batches', receipt['batch_id'])
        run = store.get('runs', receipt['run_id'])
        attempt = run['attempts'][-1]
        raw = Path(attempt['path']) / 'raw'
        postprocess_only = receipt.get('postprocess_only', False)
        verify_checkpoint(raw, receipt, job_name=attempt['job_name'], input_hash=expected['input_hash'],
                          runtime_hash=runtime_hash, cpus=run['resolved']['cpus'])
        if run['input_hash'] != expected['input_hash'] or run['resolved'] != expected['resolved']:
            raise ValueError('Restored scientific input mismatch')
        completed = solver.sta_progress(raw / (attempt['job_name'] + '.sta'), run['resolved']['duration']).get('solver_success')
        if postprocess_only and not completed:
            raise ValueError('Postprocessing continuation requires the original successful STA')
        if not completed:
            run['explicit_recover'] = True
        for lock in raw.glob(attempt['job_name'] + '*.lck'):
            lock.unlink()
        attempt['process'] = None  # never adopt an old PID on a different runner
        run.update(status='queued', phase='queued', error=None)
        store.save('runs', run)
    batch.update(status='running', pause_requested=False, stop_immediately=False)
    store.save('batches', batch)
    catalog.update(key, lambda old: {**old, 'status': 'running', 'workflow_run_id': workflow,
                                    'phase': f'Explicit continuation segment {args.segment + 1}/4'})
    # 240-minute slice leaves room for multi-GB checkpoint transfer and publication.
    deadline = time.monotonic() + max(0, 240 * 60 - (time.time() - float(os.environ['HONEYCOMB_WORKFLOW_STARTED_EPOCH'])))
    progress = Progress(github, catalog, args.job_id, store, batch['id'], deadline)
    write_json(root / 'runtime-lock.json', runtime)
    write_json(root / 'cloud-request.json', job)

    def save_solver(finished, current_batch):
        reference = publish_solver_checkpoint(root, finished, current_batch, runtime, job,
            ReleaseArchive(github, job['reserved_release_id'], tag='simulation-' + args.job_id),
            f'workflow-{workflow}', os.environ['GITHUB_SHA'])
        finished['solver_checkpoint'] = reference
        store.save('runs', finished)
        catalog.update(key, lambda old: {**old, 'solver_checkpoint': reference})

    try:
        run, history_check = execute_segment(root, store, run, batch, progress, runtime_hash, control,
            job=job, postprocess_only=postprocess_only, solver_sink=None if postprocess_only else save_solver)
        if run['status'] in ('completed', 'review'):
            publisher = ReleaseArchive(github, job['reserved_release_id'], tag='simulation-' + args.job_id)
            publisher.publish(root, attempt=f'workflow-{workflow}', complete=True)
            release = github.repo('PATCH', f'/releases/{job["reserved_release_id"]}', {'draft': False})
            catalog.update(key, lambda old: {**old, 'status': run['status'], 'archive_verified': True,
                           'release_id': release['id'], 'release_url': release['html_url'],
                           'phase': 'completed across Explicit segments',
                           'runs': [{k: run.get(k) for k in ('id', 'status', 'summary', 'quality', 'error')}]})
            outcome = 'completed'
        else:
            if progress.stop_reason != 'timed_out' or run['status'] != 'interrupted':
                raise RuntimeError('Solver failed independently of segment budget: ' + str(run.get('error')))
            attempt = run['attempts'][-1]
            raw = Path(attempt['path']) / 'raw'
            if history_check is None:
                raise RuntimeError('No verified original history for this checkpoint')
            postprocess_only = history_check.get('postprocess_only', False)
            files = checkpoint_inventory(raw, attempt['job_name'], postprocess_only=postprocess_only)
            receipt = {'segment': args.segment, 'workflow': workflow, 'child_id': args.job_id,
                       'batch_id': batch['id'], 'run_id': run['id'], 'job_name': attempt['job_name'],
                       'input_hash': run['input_hash'], 'runtime_hash': runtime_hash,
                       'cpus': run['resolved']['cpus'], 'files': files, 'orderly_checkpoint': history_check,
                       'postprocess_only': postprocess_only,
                       'progress': solver.sta_progress(raw / (attempt['job_name'] + '.sta'), run['resolved']['duration'])}
            write_json(marker, receipt)
            if args.segment == 3:
                raise RuntimeError('Four segment budget exhausted; retained checkpoint requires investigation')
            outcome = 'checkpoint'
        try:
            github.repo('PATCH', f'/check-runs/{progress.check}', {
                'status': 'completed', 'conclusion': 'neutral' if outcome == 'checkpoint' else 'success',
                'output': {'title': outcome, 'summary': 'Verified state retained for next segment' if outcome == 'checkpoint' else 'Solver and archive completed'},
            })
        except Exception:
            pass  # A convenience check update cannot invalidate verified data.
        with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
            out.write('outcome=' + outcome + '\n')
        print(json.dumps({'outcome': outcome, 'run_id': run['id'], 'segment': args.segment}), flush=True)
    except Exception as exc:
        error = str(exc)
        catalog.update(key, lambda old: {**old, 'status': 'failed', 'error': error})
        raise
    finally:
        store.db.close()


if __name__ == '__main__':
    main()

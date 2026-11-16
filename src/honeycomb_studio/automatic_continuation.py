"""One authorized handoff from a legacy timeout to verified Explicit segments."""

import base64
import hashlib
import re
import uuid

from .cloud_github import Catalog
from .models import digest
from .solver_checkpoint import PHYSICS


def recovery_plan(parent, source, policy):
    if (source['id'] != policy['source_workflow_run_id']
            or source['repository']['full_name'] != policy['repository']
            or source['head_sha'] != policy['source_sha'] or source['head_branch'] != 'main'
            or source['path'].split('@')[0] != '.github/workflows/abaqus-linux.yml'):
        raise ValueError('Source workflow differs from the authorized handoff')
    if (parent['id'] != policy['source_job_id'] or parent['input_hash'] != policy['input_hash']
            or digest(parent['spec']) != policy['input_hash']):
        raise ValueError('Frozen scientific input changed')
    if source['status'] != 'completed':
        return {'status': 'waiting_for_source'}
    if parent.get('cancel_requested') or source.get('conclusion') == 'cancelled':
        return {'status': 'cancelled'}
    if parent.get('recovery_dispatch_pending') or parent['workflow_run_id'] != source['id']:
        return {'status': 'already_requested'}
    retained, postprocess, initial = [], [], []
    for shard in parent.get('shards', []):
        if shard['status'] in ('completed', 'review') and shard.get('archive_verified'):
            retained.append(shard['index'])
        elif shard.get('solver_checkpoint') or shard.get('postprocess_source'):
            postprocess.append(shard['index'])
        elif (shard['status'] == 'timed_out' or 'timed_out' in shard.get('error', '')
              or (shard['status'] == 'blocked_environment'
                  and (source.get('conclusion') == 'timed_out'
                       or shard['index'] in source.get('timed_out_indices', [])))):
            if not policy.get('allow_initial_restart_without_checkpoint'):
                raise ValueError('No verified checkpoint; an initial recalculation is not authorized')
            initial.append(shard['index'])
        else:
            raise ValueError('Failure is not an authorized timeout or completed-ODB recovery')
    if not parent.get('shards'):
        raise ValueError('No admitted source designs')
    return dict(status='ready' if postprocess or initial else 'already_complete',
                retained_indices=retained, postprocess_only_indices=postprocess,
                initial_restart_indices=initial)


def verify_execution_source(github, policy, execution_sha):
    if github.repo('GET', '/branches/main')['commit']['sha'] != execution_sha:
        raise ValueError('Main advanced; inspect the execution source before dispatch')
    if set(policy['physics_sha256']) != {'src/honeycomb_studio/' + path for path in PHYSICS}:
        raise ValueError('Handoff must lock all six original scientific modules')
    for path, expected in policy['physics_sha256'].items():
        source = github.repo('GET', f'/contents/{path}?ref={execution_sha}')
        if hashlib.sha256(base64.b64decode(source['content'])).hexdigest() != expected:
            raise ValueError('Frozen physical source changed: ' + path)


def dispatch(github, policy, *, execution_sha):
    if github.repository != policy['repository']:
        raise ValueError('Unexpected repository')
    source = github.repo('GET', '/actions/runs/' + str(policy['source_workflow_run_id']))
    if source['status'] == 'completed' and source.get('conclusion') != 'cancelled':
        timed_out = []
        for page in range(1, 11):
            jobs = github.repo('GET', f"/actions/runs/{source['id']}/jobs?per_page=100&page={page}")['jobs']
            for job in jobs:
                match = re.match(r'^Lượt (\d+)/', job['name'])
                if match and job.get('conclusion') == 'timed_out':
                    timed_out.append(int(match[1]) - 1)
            if len(jobs) < 100:
                break
        source = {**source, 'timed_out_indices': timed_out}
    catalog = Catalog(github)
    key = 'jobs/' + policy['source_job_id']
    parent, _ = catalog.get(key)
    plan = recovery_plan(parent, source, policy)
    if plan['status'] not in ('ready', 'waiting_for_source'):
        return {**plan, 'dispatched': False}
    verify_execution_source(github, policy, execution_sha)
    if plan['status'] == 'waiting_for_source':
        return {**plan, 'dispatched': False, 'execution_source_verified': True,
                'execution_sha': execution_sha, 'source_workflow_run_id': source['id']}
    nonce = uuid.uuid4().hex

    def claim(old):
        latest = recovery_plan(old, source, policy)
        if latest['status'] == 'already_requested':
            return old
        if latest != plan:
            raise ValueError('Source results changed before handoff; inspect again')
        return {**old, 'recovery_dispatch_pending': True,
                'automatic_continuation_execution': {
                    'source_sha': execution_sha, 'source_workflow_run_id': source['id'],
                    'input_hash': old['input_hash'], 'claim': nonce,
                    'policy_sha256': digest(policy), 'plan': plan,
                    'scope': 'preserve completed siblings; verified continuation after initial handoff'}}

    saved = catalog.update(key, claim)
    if saved.get('automatic_continuation_execution', {}).get('claim') != nonce:
        return {'status': 'already_requested', 'dispatched': False}
    # The durable claim survives a lost POST response; never submit it twice.
    github.repo('POST', '/actions/workflows/abaqus-continuation.yml/dispatches', {
        'ref': 'main', 'inputs': {'job_id': policy['source_job_id'], 'recover': 'true',
                                'job_name': 'Automatic V14 timeout handoff | ' + policy['source_job_id'][:8]}})
    return {**plan, 'status': 'dispatched', 'dispatched': True,
            'execution_sha': execution_sha, 'source_workflow_run_id': source['id']}

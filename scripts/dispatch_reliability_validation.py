"""Dispatch at most six frozen-model FEA cases after the existing duration batch closes."""
import argparse
import json
import os
import uuid
from pathlib import Path

from dispatch_duration_followup import verify_execution_source

from honeycomb_studio.cloud_github import Catalog, Github
from honeycomb_studio.store import write_json
from honeycomb_studio.surrogate_validation import plan_validation, validation_identity, verification_report


def process(github, config, execution_sha):
    if github.repository != config['repository']:
        raise ValueError('Unauthorized repository')
    catalog = Catalog(github)
    identity = validation_identity(config)
    existing, _ = catalog.get('jobs/' + identity)
    if existing is not None:
        workflow = existing.get('workflow_run_id')
        if workflow is None:
            return {'status': 'already_claimed_dispatch_not_repeated', 'id': identity, 'dispatched': False}
        run = github.repo('GET', f'/actions/runs/{workflow}')
        if run['status'] != 'completed':
            return {'status': 'already_running', 'id': identity, 'workflow_run_id': workflow, 'dispatched': False}
        if (run['head_sha'] != existing['validation_context']['expected_source_sha'] or
                run.get('path') != '.github/workflows/abaqus-linux.yml' or
                run['repository']['full_name'] != config['repository']):
            raise ValueError('Verification workflow source differs from locked execution')
        if existing.get('status') not in ('completed', 'review'):
            return {'status': 'verification_needs_review_no_solver_retry', 'id': identity,
                    'workflow_run_id': workflow, 'catalog_status': existing.get('status'), 'dispatched': False}
        report = verification_report(existing, config)
        write_json(Path('output/reliability-fea-verification.json'), report)
        catalog.update('jobs/' + identity, lambda old: {**old, 'surrogate_verification': report})
        return {'status': 'verification_saved', 'id': identity, 'workflow_run_id': workflow,
                'dispatched': False, 'mae_J_kg': report['mae_J_kg'], 'mape_percent': report['mape_percent'],
                'rear_intact_count': report['rear_intact_count'], 'verified_optimum': False}
    duration, _ = catalog.get('jobs/' + config['duration_job_id'])
    if not duration or not duration.get('workflow_run_id'):
        return {'status': 'waiting_for_existing_duration_batch', 'dispatched': False}
    duration_run = github.repo('GET', f"/actions/runs/{duration['workflow_run_id']}")
    if duration_run['status'] != 'completed':
        return {'status': 'waiting_for_existing_duration_batch', 'dispatched': False,
                'prerequisite_workflow_run_id': duration_run['id']}
    source, _ = catalog.get('jobs/' + config['source_job_id'])
    document = plan_validation(source, duration, duration_run, config, execution_sha)
    if document is None:
        return {'status': 'waiting_for_duration_results_or_resource_recovery', 'dispatched': False,
                'prerequisite_workflow_run_id': duration_run['id']}
    verify_execution_source(github, config, execution_sha)
    nonce = uuid.uuid4().hex

    def claim(old):
        if old is not None:
            if old['input_hash'] != document['input_hash']:
                raise ValueError('Existing validation has different frozen inputs')
            return old
        return {**document, 'status': 'dispatching', 'dispatch_claim': nonce}

    saved = catalog.update('jobs/' + identity, claim)
    if saved.get('dispatch_claim') != nonce:
        return {'status': 'already_claimed_dispatch_not_repeated', 'id': identity, 'dispatched': False}
    # The durable claim deliberately prevents a second POST after a lost response.
    github.repo('POST', '/actions/workflows/abaqus-linux.yml/dispatches', {
        'ref': 'main', 'inputs': {'job_id': identity, 'job_name': document['name'] + ' | ' + identity[:8]}})
    return {'status': 'dispatched', 'id': identity, 'dispatched': True,
            'candidates': document['validation_context']['candidate_ids'], 'source_sha': execution_sha}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('docs/validation/reliability-study.json'))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    github = Github(token=os.environ['GITHUB_TOKEN'])
    result = process(github, config, os.environ['GITHUB_SHA'])
    write_json(Path('output/reliability-validation-controller.json'), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

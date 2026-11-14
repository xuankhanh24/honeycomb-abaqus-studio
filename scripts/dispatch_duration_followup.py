"""Dispatch the owner-authorized 12-ms follow-up once its exact source finishes."""

import argparse
import base64
import csv
import hashlib
import json
import os
import uuid
from pathlib import Path

from honeycomb_studio.cloud_github import Catalog, Github
from honeycomb_studio.duration_followup import (
    comparison_report,
    plan_followup,
    resource_recovery_indices,
    validate_followup_inputs,
)
from honeycomb_studio.store import write_json


def verify_execution_source(github, config, execution_sha):
    if github.repo('GET', '/branches/main')['commit']['sha'] != execution_sha:
        raise ValueError('Main advanced; rerun the controller at the current source')
    for path, expected in config['physics_sha256'].items():
        file = github.repo('GET', f'/contents/{path}?ref={execution_sha}')
        if hashlib.sha256(base64.b64decode(file['content'])).hexdigest() != expected:
            raise ValueError('Frozen physics module differs: ' + path)


def dispatch(github, config, *, execution_sha):
    if github.repository != config['repository']:
        raise ValueError('Follow-up repository differs from the authorized repository')
    source = github.repo('GET', f"/actions/runs/{config['source_workflow_run_id']}")
    if source['status'] != 'completed':
        plan_followup({}, source, config, execution_sha)
        return {'status': 'waiting_for_source', 'source_url': source['html_url'],
                'source_status': source['status'], 'dispatched': False}
    verify_execution_source(github, config, execution_sha)
    catalog = Catalog(github)
    parent, _ = catalog.get('jobs/' + config['source_job_id'])
    document = plan_followup(parent, source, config, execution_sha)
    if document['id'] != config.get('followup_job_id', document['id']):
        raise ValueError('Follow-up request identity differs from the fixed protocol')
    nonce = uuid.uuid4().hex

    def claim(old):
        if old is not None:
            if old['input_hash'] != document['input_hash']:
                raise ValueError('Existing follow-up has different inputs')
            return old
        return {**document, 'status': 'dispatching', 'dispatch_claim': nonce}

    saved = catalog.update('jobs/' + document['id'], claim)
    if saved.get('dispatch_claim') != nonce:
        return {'status': 'already_requested', 'id': document['id'],
                'workflow_run_id': saved.get('workflow_run_id'), 'dispatched': False}
    # Claim is durable before the POST. A lost response must be investigated,
    # never retried by a second controller invocation with a new nonce.
    github.repo('POST', '/actions/workflows/abaqus-linux.yml/dispatches', {
        'ref': 'main', 'inputs': {'job_id': document['id'],
                                'job_name': document['name'] + ' | ' + document['id'][:8]}})
    return {'status': 'dispatched', 'id': document['id'], 'dispatched': True,
            'candidate_ids': document['validation_context']['candidate_ids'],
            'source_workflow_run_id': source['id'], 'input_hash': document['input_hash'],
            'source_sha': execution_sha}


def dispatch_resource_recovery(github, catalog, followup, config, indices, execution_sha):
    verify_execution_source(github, config, execution_sha)
    nonce = uuid.uuid4().hex

    def claim(old):
        if old.get('recovery_dispatch_pending'):
            return old
        if (old.get('workflow_run_id') != followup['workflow_run_id'] or
                old['input_hash'] != followup['input_hash'] or resource_recovery_indices(old) != indices):
            raise ValueError('Follow-up changed before resource recovery claim')
        history = old.get('duration_execution_history', []) + [{
            'workflow_run_id': old['workflow_run_id'],
            'source_sha': old['validation_context']['expected_source_sha'],
            'resource_blocked_indices': indices}]
        return {**old, 'validation_context': {**old['validation_context'], 'expected_source_sha': execution_sha},
                'duration_execution_history': history, 'duration_resource_recovery_count': 1,
                'recovery_dispatch_pending': True, 'resource_recovery_claim': nonce}

    saved = catalog.update('jobs/' + followup['id'], claim)
    if saved.get('resource_recovery_claim') != nonce:
        return {'status': 'resource_recovery_already_requested', 'id': followup['id'], 'dispatched': False}
    github.repo('POST', '/actions/workflows/abaqus-linux.yml/dispatches', {
        'ref': 'main', 'inputs': {'job_id': followup['id'], 'recover': 'true',
                                'job_name': 'Duration verification 8-12 ms | resource recovery | ' + followup['id'][:8]}})
    names = followup['validation_context']['candidate_ids']
    return {'status': 'resource_recovery_dispatched', 'id': followup['id'], 'dispatched': True,
            'recovered_candidate_ids': [names[i] for i in indices],
            'retained_candidate_ids': [name for i, name in enumerate(names) if i not in indices]}


def collect_comparison(github, config, workflow_id, *, execution_sha):
    catalog = Catalog(github)
    followup, _ = catalog.get('jobs/' + config['followup_job_id'])
    if not followup or followup.get('workflow_run_id') != workflow_id:
        raise ValueError('Unexpected completed follow-up workflow')
    if followup.get('recovery_dispatch_pending'):
        return {'status': 'resource_recovery_already_requested', 'id': followup['id'], 'dispatched': False}
    run = github.repo('GET', f'/actions/runs/{workflow_id}')
    if (run['status'] != 'completed' or run['head_sha'] != followup['validation_context']['expected_source_sha'] or
            run['repository']['full_name'] != config['repository']):
        raise ValueError('Follow-up workflow identity is not complete or does not match')
    source = github.repo('GET', f"/actions/runs/{config['source_workflow_run_id']}")
    parent, _ = catalog.get('jobs/' + config['source_job_id'])
    validate_followup_inputs(parent, followup, source, config)
    indices = resource_recovery_indices(followup)
    if indices:
        return dispatch_resource_recovery(github, catalog, followup, config, indices, execution_sha)
    report = comparison_report(parent, followup, source, config)
    write_json(Path('output/duration-comparison.json'), report)
    with Path('output/duration-comparison.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(report['cases'][0]))
        writer.writeheader()
        writer.writerows(report['cases'])
    text = ['# Kiểm chứng thời lượng 8–12 ms', '',
            '| Ca | SEA 8 ms (J/kg) | SEA 12 ms (J/kg) | Chênh lệch / SEA 12 ms (%) | Hỏng mặt đáy 8 / 12 ms | Sự kiện kết thúc ở 12 ms |',
            '|---|---:|---:|---:|---|---|']
    for row in report['cases']:
        text.append(f"| {row['candidate_id']} | {row['SEA_at_8ms_J_kg']:.4f} | {row['SEA_at_12ms_J_kg']:.4f} | "
                    f"{row['SEA_change_relative_to_12_percent']:.3f} | {row['rear_skin_deleted_at_8ms']} / "
                    f"{row['rear_skin_deleted_at_12ms']} | {row['12ms_event_finished']} |")
    text += ['', 'Ngưỡng so sánh 2% là tiêu chí dự án. Kiểm tra thời lượng trên hai ca không thay thế kiểm chứng thực nghiệm.',
             'Nếu sự kiện chưa kết thúc ở 12 ms, chưa thể kết luận 12 ms đủ. Bộ 489 mẫu và mô hình đã khớp không được cập nhật.']
    Path('output/duration-comparison.md').write_text('\n'.join(text) + '\n', encoding='utf-8')
    catalog.update('jobs/' + followup['id'], lambda old: {**old, 'duration_comparison': report})
    return {'status': 'comparison_saved', 'id': followup['id'], 'dispatched': False,
            'candidate_ids': followup['validation_context']['candidate_ids']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('docs/validation/s1-s5-duration-followup.json'))
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    triggering_id = event.get('workflow_run', {}).get('id', config['source_workflow_run_id'])
    github = Github(token=os.environ['GITHUB_TOKEN'])
    if triggering_id == config['source_workflow_run_id']:
        result = dispatch(github, config, execution_sha=os.environ['GITHUB_SHA'])
    else:
        result = collect_comparison(github, config, triggering_id, execution_sha=os.environ['GITHUB_SHA'])
    write_json(Path('output/duration-followup.json'), result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

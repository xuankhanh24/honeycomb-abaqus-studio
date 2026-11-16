"""Arm/check the owner-authorized V14 handoff without interrupting live solvers."""

import json
import os
from pathlib import Path

from honeycomb_studio.automatic_continuation import dispatch
from honeycomb_studio.cloud_github import Github
from honeycomb_studio.store import write_json


def main():
    policy = json.loads(Path('docs/validation/v14-automatic-continuation.json').read_text(encoding='utf-8'))
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    if event.get('workflow_run', {}).get('id', policy['source_workflow_run_id']) != policy['source_workflow_run_id']:
        raise ValueError('Unexpected triggering workflow')
    result = dispatch(Github(token=os.environ['GITHUB_TOKEN']), policy, execution_sha=os.environ['GITHUB_SHA'])
    write_json(Path('output/automatic-continuation.json'), result)
    with Path(os.environ['GITHUB_STEP_SUMMARY']).open('a', encoding='utf-8') as stream:
        stream.write('```json\n' + json.dumps(result, ensure_ascii=False, indent=2) + '\n```\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

"""Certify a finished wave checkpoint using immutable assets and archived run records."""

from copy import deepcopy
from pathlib import PurePosixPath

from .cloud_restore import validate_manifest


def completed_checkpoint(checkpoint, assets, runs):
    validate_manifest(checkpoint, allow_incomplete=True)
    if not runs or any(r.get('status') != 'completed' or not r.get('quality', {}).get('ml_eligible')
                       or not r.get('quality', {}).get('solver_completed') for r in runs):
        raise ValueError('Checkpoint is not a numerically accepted, finished solver wave')
    inventory = {a['id']: a for a in assets}
    for file in checkpoint['files']:
        for part in file['parts']:
            asset = inventory.get(part['asset_id'])
            if (not asset or asset.get('digest') != part['digest'] or asset['size'] != part['bytes']
                    or asset['browser_download_url'] != part['url']):
                raise ValueError('Missing or changed checkpoint asset')
    for run in runs:
        files = [f['path'] for f in checkpoint['files'] if f"/runs/{run['id']}/" in f['path']]
        names = {PurePosixPath(path).name for path in files}
        if not {'run.json', 'solver-complete.json', 'quality.json', 'summary.json',
                'complete.json', 'impact_history.csv'} <= names or not any(p.endswith('.odb') for p in files):
            raise ValueError('Checkpoint lacks original solver output or numerical exports')
    result = deepcopy(checkpoint)
    result['complete'] = True
    result['recovery'] = {'method': 'completed-wave-checkpoint', 'solver_rerun': False,
                          'run_ids': [r['id'] for r in runs], 'verified_asset_parts': sum(
                              len(f['parts']) for f in checkpoint['files'])}
    return result

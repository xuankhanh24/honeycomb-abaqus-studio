"""Freeze recomputed predictions and physically identical FEA inputs before dispatch."""
import argparse
import json
import math
from pathlib import Path

import joblib
import numpy as np
from run_reliability_study import predict_bundle

from honeycomb_studio.models import ModelSpec, digest
from honeycomb_studio.surrogate_reliability import FEATURES, sha256, write_json
from honeycomb_studio.surrogate_validation import validation_identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', type=Path, required=True)
    parser.add_argument('--validation-dir', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--source-config', type=Path, default=Path('docs/validation/s1-s5-duration-followup.json'))
    args = parser.parse_args()
    if args.config.exists():
        raise ValueError('Use a new frozen validation configuration')
    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))
    source_config = read(args.source_config)
    lock = read(args.study / 'model-lock.json')
    protocol = read(args.study / 'protocol.json')
    proposals = read(args.study / 'fea-proposals.json')['candidates']
    if (sha256(args.study / 'research-models.joblib') != lock['model_sha256'] or
            sha256(args.study / 'protocol.json') != lock['protocol_sha256']):
        raise ValueError('Model/protocol lock failed')
    if not 1 <= len(proposals) <= 6:
        raise ValueError('One to six frozen proposals required')
    # Only load the locally fitted, checksum-verified model created by this study.
    bundle = joblib.load(args.study / 'research-models.joblib')
    x = np.array([[row[key] for key in FEATURES] for row in proposals])
    predicted, probability, width, _, info = predict_bundle(bundle, x)
    source = read(args.validation_dir / 'status-3bc66c62749746a7839df1a87392d798.json')
    if (source['id'] != source_config['source_job_id'] or digest(source['spec']) != source_config['source_input_hash']):
        raise ValueError('Frozen source input changed')
    template = ModelSpec.model_validate(source['spec']['model']).resolved()
    allowed = set(FEATURES) | {'reentrant_inclined_length_mm', 'periodic_density_kg_m3',
                               'reentrant_indent', 'reentrant_angle_to_z_deg',
                               'duration', 'field_intervals', 'history_intervals'}
    candidates = []
    for i, row in enumerate(proposals):
        for actual, saved in ((predicted[i], row['predicted_SEA_J_kg']), (probability[i], row['p_delete']),
                              (predicted[i] - width[i], row['lower_SEA_J_kg']),
                              (predicted[i] + width[i], row['upper_SEA_J_kg'])):
            if not math.isclose(actual, saved, rel_tol=1.e-10, abs_tol=1.e-8):
                raise ValueError('Saved proposal differs from locked model prediction')
        if not info['eligible'][i] or probability[i] > .1:
            raise ValueError('Proposal does not meet the research acquisition rule')
        model = ModelSpec.model_validate({**source['spec']['model'], **{key: row[key] for key in FEATURES},
                                          'duration': .012, 'field_intervals': 1200, 'history_intervals': 6000}).resolved()
        changed = {key for key in template if template[key] != model[key]}
        if (changed - allowed or model['duration'] != .012 or model['cpus'] != 4 or
                not math.isclose(model['duration'] / model['field_intervals'],
                                 template['duration'] / template['field_intervals']) or
                not math.isclose(model['duration'] / model['history_intervals'],
                                 template['duration'] / template['history_intervals'])):
            raise ValueError('FEA input would change frozen physics, mesh or duration')
        candidates.append({**row, 'study_candidate_id': row['candidate_id'], 'candidate_id': f'V6-{i + 1:02d}'})
    config = {'repository': source_config['repository'], 'duration_job_id': source_config['followup_job_id'],
              'source_job_id': source_config['source_job_id'], 'source_input_hash': source_config['source_input_hash'],
              'physics_sha256': source_config['physics_sha256'], 'model_sha256': lock['model_sha256'],
              'study_protocol_sha256': lock['protocol_sha256'], 'study_revision': protocol['revision'],
              'study_results_sha256': sha256(args.study / 'results.json'),
              'candidate_file_sha256': sha256(args.study / 'fea-proposals.json'),
              'target_duration_s': .008, 'simulation_duration_s': .012,
              'automatic_retraining': False, 'candidates': candidates}
    write_json(args.config, config)
    write_json(args.config.with_name('reliability-study-preflight.json'), {
        'status': 'input_and_prediction_preflight_passed', 'solver_executed': False,
        'job_id': validation_identity(config), 'model_sha256': lock['model_sha256'],
        'config_sha256': sha256(args.config), 'candidate_count': len(candidates),
        'predictions_recomputed_from_locked_model': True, 'output_cadence_preserved': True,
        'changed_parameters': [*FEATURES, 'duration', 'field_intervals', 'history_intervals'],
        'physical_validation': 'not_established'})
    print(json.dumps({'status': 'frozen', 'job_id': validation_identity(config), 'cases': len(candidates)}))


if __name__ == '__main__':
    main()

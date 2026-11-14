"""Extract a strictly sampled earlier horizon from completed native histories.

No solver is run. Categorical deletion labels are never interpolated, and full
12-ms outcomes cannot substitute for an 8-ms label. Official eligibility stays
unchanged; this is an auditable numerical subwindow, not physical validation.
"""
import csv
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np

HORIZON_SAMPLE_TOLERANCE_S = 1.e-7


def _times(values, duration, interval):
    values = np.asarray(values, float)
    if (values.ndim != 1 or len(values) < 3 or not np.isfinite(values).all() or
            np.any(np.diff(values) <= 0) or np.diff(values).max() > 1.5 * interval + 1.e-8 or
            abs(values[0]) > 1.e-8 or abs(values[-1] - duration) > 1.e-8):
        raise ValueError('Incomplete, gapped or unordered native horizon evidence')
    return values


def _sample_index(times, horizon):
    index = int(np.argmin(abs(times - horizon)))
    if abs(times[index] - horizon) > HORIZON_SAMPLE_TOLERANCE_S:
        raise ValueError('No native sample at the requested horizon; refusing label interpolation')
    return index


def seal_horizon_summary(directory: Path, resolved: dict, native: dict, horizon: float, input_hash: str):
    duration = resolved['duration']
    if (not isinstance(horizon, (int, float)) or isinstance(horizon, bool) or not math.isfinite(horizon) or
            not 0 < horizon < duration or native.get('solver_completed') is not True or
            native.get('history_integrity_passed') is not True or native.get('damage_fields_complete') is not True or
            not math.isclose(native.get('last_time_s', 0), duration, abs_tol=1.e-8, rel_tol=0)):
        raise ValueError('Only completed, complete native evidence can provide an earlier horizon')
    if not isinstance(input_hash, str) or len(input_hash) != 64 or any(c not in '0123456789abcdef' for c in input_hash):
        raise ValueError('Missing native input provenance')
    mass = native.get('core_mass_kg')
    if not isinstance(mass, (int, float)) or isinstance(mass, bool) or not math.isfinite(mass) or mass <= 0:
        raise ValueError('Initial core mass unavailable')
    history_bytes = (directory / 'impact_history.csv').read_bytes()
    rear_bytes = (directory / 'rear-field-history.json').read_bytes()
    history = list(csv.DictReader(io.StringIO(history_bytes.decode('utf-8-sig'))))
    rear = json.loads(rear_bytes)
    times = _times([float(r['time_s']) for r in history], duration, duration / resolved['history_intervals'])
    rear_times = _times([r['time_s'] for r in rear], duration, duration / resolved['field_intervals'])
    end, rear_end = _sample_index(times, horizon), _sample_index(rear_times, horizon)
    energy = np.array([float(r['CORE_ALLPD_J']) + float(r['CORE_ALLDMD_J']) for r in history])
    force = np.array([float(r['contact_force_N']) for r in history])
    velocity = np.array([float(r['velocity_mm_s']) for r in history])
    displacement = np.array([r['rear_downward_mm'] for r in rear], float)
    deleted = [r['rear_deleted_elements'] for r in rear]
    if (not np.isfinite([energy, force, velocity]).all() or not np.isfinite(displacement).all() or
            np.any(energy < -1.e-9) or np.any(displacement < 0) or
            any(type(v) is not int or v < 0 for v in deleted)):
        raise ValueError('Nonfinite energy/motion or invalid categorical deletion evidence')
    for key, value in (('core_dissipation_J', energy[-1]), ('SEA_core_J_kg', energy[-1] / mass)):
        saved = native.get(key)
        if (not isinstance(saved, (int, float)) or isinstance(saved, bool) or not math.isfinite(saved) or
                not math.isclose(float(value), saved, rel_tol=1.e-8, abs_tol=1.e-8)):
            raise ValueError('Native CSV endpoint disagrees with completed summary: ' + key)
    if native.get('rear_skin_deleted') is not (max(deleted) > 0):
        raise ValueError('Native rear history disagrees with completed damage summary')
    prefix_energy, prefix_force = energy[:end + 1], force[:end + 1]
    tail = times[:end + 1] >= times[end] - .0005
    force_limit = max(1., .01 * float(prefix_force.max()))
    stable = float(np.ptp(prefix_energy[tail])) <= .01 * max(float(prefix_energy[-1]), 1.e-6)
    bottom_deleted = max(deleted[:rear_end + 1])
    summary = {'target_horizon_s': horizon, 'last_time_s': float(times[end]),
               'core_mass_kg': mass, 'core_dissipation_J': float(energy[end]),
               'SEA_core_J_kg': float(energy[end] / mass),
               'rear_skin_deleted': bottom_deleted > 0, 'deleted_BOTTOM_elements': bottom_deleted,
               'max_rear_downward_mm': float(displacement[:rear_end + 1].max()),
               'rear_end_downward_mm': float(displacement[rear_end]),
               'event_finished': bool(abs(prefix_force[tail]).max() <= force_limit and stable),
               'end_contact_force_N': float(force[end]), 'end_impactor_velocity_m_s': float(velocity[end] / 1000),
               'history_sample_count': end + 1, 'rear_frame_count': rear_end + 1}
    receipt = {'available': True, 'horizon_s': horizon, 'simulation_duration_s': duration,
               'input_hash': input_hash, 'summary': summary,
               'source_sha256': {'impact_history.csv': hashlib.sha256(history_bytes).hexdigest(),
                                 'rear-field-history.json': hashlib.sha256(rear_bytes).hexdigest()},
               'native_sample_time_s': {'history': float(times[end]), 'rear': float(rear_times[rear_end])},
               'sample_time_tolerance_s': HORIZON_SAMPLE_TOLERANCE_S,
               'native_sample_offset_s': {'history': float(times[end] - horizon),
                                          'rear': float(rear_times[rear_end] - horizon)},
               'interpolated_deletion_label': False, 'official_ml_eligibility_override': False,
               'physical_validation': 'not_established'}
    output = directory / f'horizon-{horizon * 1000:g}ms.json'
    output.write_text(json.dumps(receipt, indent=2, allow_nan=False), encoding='utf-8')
    return receipt

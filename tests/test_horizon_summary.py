"""Prevent a later damage/energy state from contaminating an earlier ML target."""
import csv
import hashlib
import json
from copy import deepcopy

import pytest

from honeycomb_studio.horizon_summary import seal_horizon_summary


def native_fixture(tmp_path):
    history = []
    rear = []
    for i in range(13):
        time = i / 1000
        history.append({'time_s': time, 'CORE_ALLPD_J': 2. * min(i, 9), 'CORE_ALLDMD_J': 0.,
                        'contact_force_N': 100. if i < 9 else 0., 'velocity_mm_s': -1000.})
        rear.append({'time_s': time, 'rear_downward_mm': float(i), 'rear_deleted_elements': 4 if i >= 9 else 0})
    with (tmp_path / 'impact_history.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(history[0]))
        writer.writeheader()
        writer.writerows(history)
    (tmp_path / 'rear-field-history.json').write_text(json.dumps(rear), encoding='utf-8')
    resolved = {'duration': .012, 'history_intervals': 12, 'field_intervals': 12}
    native = {'solver_completed': True, 'history_integrity_passed': True, 'damage_fields_complete': True,
              'last_time_s': .012, 'core_mass_kg': .02, 'rear_skin_deleted': True, 'event_finished': True,
              'SEA_core_J_kg': 900., 'core_dissipation_J': 18.}
    return resolved, native


def test_separate_8ms_energy_damage_and_event_from_completed_12ms_run(tmp_path):
    resolved, native = native_fixture(tmp_path)
    before = deepcopy(native)
    receipt = seal_horizon_summary(tmp_path, resolved, native, .008, 'a' * 64)
    short = receipt['summary']
    assert short['SEA_core_J_kg'] == 800. and short['core_dissipation_J'] == 16.
    assert short['rear_skin_deleted'] is False and short['event_finished'] is False
    assert native == before and native['rear_skin_deleted'] is True
    assert receipt['official_ml_eligibility_override'] is False
    assert receipt['interpolated_deletion_label'] is False
    assert short['history_sample_count'] == short['rear_frame_count'] == 9
    assert short['max_rear_downward_mm'] == 8.
    assert receipt['source_sha256']['impact_history.csv'] == hashlib.sha256(
        (tmp_path / 'impact_history.csv').read_bytes()).hexdigest()
    assert (tmp_path / 'horizon-8ms.json').is_file()


def test_categorical_deletion_is_never_interpolated_between_native_frames(tmp_path):
    resolved, native = native_fixture(tmp_path)
    with pytest.raises(ValueError, match='native sample'):
        seal_horizon_summary(tmp_path, resolved, native, .0085, 'a' * 64)


def test_native_explicit_increment_offset_is_retained_and_bounded(tmp_path):
    resolved, native = native_fixture(tmp_path)
    path = tmp_path / 'rear-field-history.json'
    rear = json.loads(path.read_text())
    rear[8]['time_s'] += 5.9e-8  # Measured native output offsets up to ~59.4 ns.
    path.write_text(json.dumps(rear))
    receipt = seal_horizon_summary(tmp_path, resolved, native, .008, 'a' * 64)
    assert receipt['native_sample_offset_s']['rear'] == pytest.approx(5.9e-8)
    assert receipt['interpolated_deletion_label'] is False


@pytest.mark.parametrize('problem', ['missing_frame', 'nan_energy', 'unknown_deleted', 'unordered',
                                    'no_mass', 'no_integrity', 'wrong_end', 'wrong_provenance'])
def test_missing_or_inconsistent_native_evidence_blocks_horizon_receipt(tmp_path, problem):
    resolved, native = native_fixture(tmp_path)
    if problem in ('missing_frame', 'unknown_deleted', 'unordered'):
        path = tmp_path / 'rear-field-history.json'
        rows = json.loads(path.read_text())
        if problem == 'missing_frame':
            rows.pop(8)
        elif problem == 'unknown_deleted':
            rows[8]['rear_deleted_elements'] = None
        else:
            rows[7], rows[8] = rows[8], rows[7]
        path.write_text(json.dumps(rows))
    elif problem == 'nan_energy':
        path = tmp_path / 'impact_history.csv'
        path.write_text(path.read_text().replace('16.0,0.0', 'nan,0.0'))
    elif problem == 'no_mass':
        native['core_mass_kg'] = None
    elif problem == 'no_integrity':
        native['history_integrity_passed'] = False
    elif problem == 'wrong_end':
        native['last_time_s'] = .010
    with pytest.raises((ValueError, TypeError)):
        seal_horizon_summary(tmp_path, resolved, native, .008, '' if problem == 'wrong_provenance' else 'a' * 64)
    assert not (tmp_path / 'horizon-8ms.json').exists()

"""Prevent optimistic safety claims, target mixing and leakage in surrogate studies."""
import math

import numpy as np
import pytest
from scipy.stats import binomtest

from honeycomb_studio.surrogate_reliability import (
    FEATURES,
    PROTOCOL,
    DesignDomain,
    acquisition_mask,
    audit_rows,
    boolean,
    conformal_radius,
    geometry_features,
    load_source,
    regression_metrics,
    release_gates,
    risk_upper,
    screening_counts,
    select_threshold,
)


def source_row():
    return {'design_id': 'example', **dict(zip(FEATURES, [30., .07, 7., 4.], strict=True)),
            'core_mass_kg': .02, 'core_dissipation_J': 20., 'SEA_core_J_kg': 1000.,
            'numerical_passed': True, 'archive_verified_current': True, 'damage_fields_complete': True,
            'history_integrity_passed': True, 'solver_completed': True, 'duration': .008,
            'velocity_m_s': 6.5, 'rear_skin_deleted': False, 'event_finished': False,
            'ml_development_eligible': False}


@pytest.mark.parametrize('value', ['', None, 'unknown', 'nan', 0, 1])
def test_missing_boolean_evidence_is_never_assumed_false(value):
    with pytest.raises(ValueError):
        boolean(value)


def test_incomplete_event_scope_is_preserved():
    report = audit_rows([source_row()])
    assert report['official_ml_eligible'] == report['event_finished'] == 0
    assert report['scope'] == 'exploratory_fixed_horizon_only'


@pytest.mark.parametrize(('field', 'value'), [
    ('duration', .012), ('velocity_m_s', 15.), ('SEA_core_J_kg', 1.),
    ('core_mass_kg', 0.), ('damage_fields_complete', False),
    ('numerical_passed', None), ('ml_development_eligible', True), ('foil', float('nan')),
])
def test_source_admission_rejects_inconsistent_or_unverified_rows(field, value):
    with pytest.raises(ValueError):
        audit_rows([{**source_row(), field: value}])


def test_duplicate_geometry_cannot_leak_across_split_ids():
    with pytest.raises(ValueError, match='duplicate geometry'):
        audit_rows([source_row(), {**source_row(), 'design_id': 'another-id'}])


def test_wrong_frozen_source_is_rejected_before_reading_zip(tmp_path):
    archive = tmp_path / 'wrong.zip'
    archive.write_bytes(b'wrong source')
    with pytest.raises(ValueError, match='immutable source'):
        load_source(archive)


@pytest.mark.parametrize(('k', 'n'), [(0, 41), (0, 59), (1, 100), (12, 30), (10, 10)])
def test_one_sided_risk_bound_matches_independent_scipy_calculation(k, n):
    expected = binomtest(k, n, alternative='less').proportion_ci(.95, method='exact').high
    assert risk_upper(k, n) == pytest.approx(expected)


def test_zero_observed_failures_does_not_mean_zero_risk():
    assert risk_upper(0, 41) > .05
    assert risk_upper(0, 59) < .05
    assert risk_upper(0, 0) == 1.


def test_insufficient_screening_evidence_abstains():
    threshold, rows = select_threshold(np.zeros(82), np.full(82, .0001), np.ones(82, bool))
    assert threshold is None  # Even 82 perfect acceptances cannot meet the simultaneous bound.
    assert all(r['upper_risk'] > .05 for r in rows)
    result = screening_counts(np.zeros(82), np.zeros(82), np.ones(82, bool), threshold)
    assert result['accepted'] == 0 and result['upper_risk'] == 1.


def test_sufficient_calibration_evidence_can_accept_a_fixed_rule():
    threshold, _ = select_threshold(np.zeros(200), np.full(200, .0001), np.ones(200, bool))
    assert threshold == .1


def test_nonfinite_probability_blocks_screening():
    with pytest.raises(ValueError):
        screening_counts([0], [float('nan')], [True], .1)


def test_acquisition_rejects_unsupported_or_known_failures_before_expensive_inference():
    keep = acquisition_mask([True, False, True, True, True], [.05, .01, .11, .01, .01],
                            [.2, .2, .2, .2, .001], [.2, .2, .2, .02, .2])
    assert keep.tolist() == [True, False, False, False, False]
    with pytest.raises(ValueError):
        acquisition_mask([True], [float('nan')], [.1], [.1])


def test_split_conformal_uses_finite_sample_order_statistic():
    assert conformal_radius(np.arange(1, 21), .1) == 19
    assert math.isinf(conformal_radius([1., 2.], .05))


def test_geometry_features_depend_only_on_inputs_and_reject_invalid_throat():
    x = np.array([[30., .07, 7., 4.]])
    features = geometry_features(x)
    assert features.shape == (1, 10)
    assert features[0, 4] == pytest.approx(7 - 4 * np.tan(np.deg2rad(30)))
    np.testing.assert_array_equal(features[:, :4], x)
    with pytest.raises(ValueError):
        geometry_features([[45., .07, 4.5, 7.]])


def domain_fixture():
    rng = np.random.default_rng(4)
    x = rng.uniform([25., .05, 7., 3.], [32., .09, 8.2, 5.], size=(120, 4))
    deleted = np.zeros(120, int)
    deleted[20] = 1
    return DesignDomain(x, deleted), x


def test_known_failed_design_is_vetoed_even_with_low_classifier_probability():
    domain, x = domain_fixture()
    result = domain.evaluate(x[[20]])
    assert not result['eligible'][0]
    safety = screening_counts([1], [.00001], result['eligible'], .1)
    assert safety['accepted'] == 0


def test_nearby_failure_and_extrapolation_are_rejected():
    domain, x = domain_fixture()
    nearby = x[20].copy()
    nearby[0] += .01
    assert not domain.evaluate([nearby])['eligible'][0]
    assert not domain.evaluate([[44., .11, 8., 3.]])['eligible'][0]
    with pytest.raises(ValueError):
        domain.evaluate([[float('nan'), .05, 8., 4.]])


def test_perfect_regression_is_insufficient_for_optimum_promotion():
    pytest.importorskip('sklearn')
    metrics = regression_metrics(np.arange(100, 140), np.arange(100, 140), np.ones(40))
    safety = {'accepted': 100, 'upper_risk': .03}
    gates = release_gates(metrics, safety)
    assert not gates['passed']
    assert {'fresh_fea', 'duration_converged', 'event_finished', 'mesh_converged',
            'physical_validated'} <= set(gates['failed'])


def test_zero_target_does_not_generate_misleading_percentage_metrics():
    pytest.importorskip('sklearn')
    metrics = regression_metrics([0., 100.], [1., 102.])
    assert metrics['mape_percent'] == 2.
    assert metrics['relative_metric_excluded_zero_targets'] == 1
    assert PROTOCOL['official_ml_eligibility_override'] is False

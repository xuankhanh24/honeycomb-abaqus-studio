"""Auditable fixed-horizon surrogate research; never a physical safety certificate.

The optional campaign extra supplies scikit-learn. Data validation, risk bounds
and design screening deliberately remain usable without that optional extra.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import ConvexHull, KDTree
from scipy.stats import beta

FEATURES = ('reentrant_delta_deg', 'foil', 'cell_size', 'reentrant_cell_height')
TARGET = 'SEA_core_J_kg'
BOUNDS = np.array([[25., 45.], [.035, .115], [4.5, 8.2], [3., 7.]])
SOURCE_SHA256 = '59b74b9678f848a3b80fec56202656cf04d68d4bd7fda599e9cc315b99875825'
SEED = 20261114
PROTOCOL: dict[str, Any] = {
    'revision': 'reliability-v5', 'seed': SEED, 'target': 'core_SEA_at_8ms_J_kg',
    'duration_s': .008, 'velocity_m_s': 6.5, 'features': FEATURES,
    'outer_folds': 5, 'inner_folds': 3, 'split_fractions': [.6, .2, .2],
    'threshold_grid': [.001, .005, .01, .02, .03, .05, .075, .1],
    'risk_limit': .05, 'risk_alpha': .05, 'interval_alpha': .05,
    'failure_exclusion_radius_normalized': .05, 'support_quantile': .95,
    'qualification_mae_J_kg': 20., 'qualification_mape_percent': 2.,
    'qualification_ape_q95_percent': 5., 'qualification_min_coverage': .9,
    'qualification_min_samples': 30, 'candidate_count': 6,
    'candidate_pool': 16384, 'candidate_spacing_normalized': .075,
    'official_ml_eligibility_override': False, 'physical_validation': 'not_established',
    'new_fea_required_for_promotion': True,
}


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def read_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        Path(path).write_text('', encoding='utf-8-sig')
        return
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def boolean(value):
    if value is True or value == 'True':
        return True
    if value is False or value == 'False':
        return False
    raise ValueError(f'Missing/invalid boolean evidence: {value!r}')


def audit_rows(rows):
    """Do not silently reinterpret incomplete-event rows as full-event ML data."""
    if not rows or len({row['design_id'] for row in rows}) != len(rows):
        raise ValueError('Empty data or repeated design IDs')
    seen = set()
    for row in rows:
        x = tuple(float(row[name]) for name in FEATURES)
        if not np.isfinite(x).all() or x in seen:
            raise ValueError('Nonfinite or duplicate geometry')
        if np.any(np.asarray(x) < BOUNDS[:, 0]) or np.any(np.asarray(x) > BOUNDS[:, 1]):
            raise ValueError('Geometry outside the frozen campaign bounds')
        seen.add(x)
        mass, energy, sea = (float(row[k]) for k in ('core_mass_kg', 'core_dissipation_J', TARGET))
        if not np.isfinite([mass, energy, sea]).all() or mass <= 0 or energy < 0 or sea < 0:
            raise ValueError('Invalid mass/energy/SEA')
        if not math.isclose(sea, energy / mass, rel_tol=1.e-9, abs_tol=1.e-9):
            raise ValueError('SEA identity failed')
        for key in ('numerical_passed', 'archive_verified_current', 'damage_fields_complete',
                    'history_integrity_passed', 'solver_completed'):
            if not boolean(row[key]):
                raise ValueError('Required evidence failed: ' + key)
        if not math.isclose(float(row['duration']), .008, abs_tol=1.e-12):
            raise ValueError('Mixed duration targets')
        if not math.isclose(float(row['velocity_m_s']), 6.5, abs_tol=1.e-12):
            raise ValueError('Mixed impact velocities')
        boolean(row['rear_skin_deleted'])
        boolean(row['event_finished'])
        if boolean(row['ml_development_eligible']):
            raise ValueError('Official-eligibility scope changed; audit separately')
    return {'count': len(rows), 'unique_inputs': len(seen),
            'event_finished': sum(boolean(r['event_finished']) for r in rows),
            'official_ml_eligible': 0, 'scope': 'exploratory_fixed_horizon_only'}


def load_source(archive):
    if sha256(archive) != SOURCE_SHA256:
        raise ValueError('Wrong immutable source archive')
    with zipfile.ZipFile(archive) as package:
        for line in package.read('CHECKSUMS.sha256').decode().splitlines():
            expected, name = line.split(maxsplit=1)
            if hashlib.sha256(package.read(name.strip())).hexdigest() != expected:
                raise ValueError('Archive member checksum failed: ' + name)
        def table(name):
            return list(csv.DictReader(io.StringIO(package.read('csv/' + name + '.csv').decode('utf-8-sig'))))
        rows = table('samples_all_489')
        resolved = {r['design_id']: r for r in table('resolved_inputs_completed')}
        requested = {r['design_id']: r for r in table('inputs_all_489')}
    report = audit_rows(rows)
    roles = {role: sum(r['role'] == role for r in rows) for role in ('development', 'test')}
    if roles != {'development': 411, 'test': 78} or len(rows) != 489:
        raise ValueError('Frozen 411/78 split changed')
    ids = {r['design_id'] for r in rows}
    if set(resolved) != ids or set(requested) != ids:
        raise ValueError('Input provenance IDs differ')
    for row in rows:
        for name in FEATURES:
            values = [float(row[name]), float(resolved[row['design_id']]['resolved.' + name]),
                      float(requested[row['design_id']]['input.' + name])]
            if not np.allclose(values, values[0], rtol=1.e-12, atol=1.e-12):
                raise ValueError('Requested/resolved feature mismatch')
        for name, expected in (('duration', .008), ('velocity_m_s', 6.5)):
            if not math.isclose(float(resolved[row['design_id']]['resolved.' + name]), expected,
                                abs_tol=1.e-12):
                raise ValueError('Resolved duration/velocity mismatch')
    return rows, {**report, 'roles': roles, 'source_sha256': SOURCE_SHA256,
                  'all_member_hashes_verified': True, 'requested_resolved_features_match': True}


def arrays(rows):
    return (np.asarray([[float(r[k]) for k in FEATURES] for r in rows]),
            np.asarray([float(r[TARGET]) for r in rows]),
            np.asarray([boolean(r['rear_skin_deleted']) for r in rows], dtype=int))


def geometry_features(x):
    """Only quantities available before FEA; no response, damage or label inputs."""
    x = np.atleast_2d(np.asarray(x, float))
    if x.shape[1] != 4 or not np.isfinite(x).all():
        raise ValueError('Expected finite four-dimensional geometry')
    delta, foil, width, height = x.T
    angle = np.deg2rad(delta)
    throat = width - height * np.tan(angle)
    if np.any(throat <= 0) or np.any(foil <= 0) or np.any(height <= 0):
        raise ValueError('Invalid derived geometry')
    return np.column_stack((x, throat, height / (2 * np.cos(angle)), foil / width,
                            foil / height, height / width, foil / throat))


def risk_upper(failures, accepted, alpha=.05):
    """One-sided Clopper-Pearson bound, conditional on binomial sampling assumptions."""
    if (not 0 < alpha < 1 or not isinstance(accepted, (int, np.integer)) or
            not isinstance(failures, (int, np.integer)) or not 0 <= failures <= accepted):
        raise ValueError('Invalid binomial counts/alpha')
    if accepted == 0 or failures == accepted:
        return 1.
    return float(beta.ppf(1 - alpha, failures + 1, accepted - failures))


def screening_counts(labels, probability, eligible, threshold, alpha=.05) -> dict[str, Any]:
    labels = np.asarray(labels)
    probability = np.asarray(probability, float)
    eligible = np.asarray(eligible, bool)
    if (labels.shape != probability.shape or labels.shape != eligible.shape or
            not np.isin(labels, [0, 1]).all() or not np.isfinite(probability).all() or
            np.any((probability < 0) | (probability > 1))):
        raise ValueError('Invalid screening evidence')
    accepted = np.zeros(len(labels), bool) if threshold is None else eligible & (probability <= threshold)
    n, k = int(accepted.sum()), int(labels[accepted].sum())
    return {'accepted': n, 'deleted_among_accepted': k, 'upper_risk': risk_upper(k, n, alpha),
            'confidence': 1 - alpha, 'assumption': 'binomial_exchangeable_designs'}


def select_threshold(labels, probability, eligible, grid=None, risk_limit=.05, alpha=.05):
    grid = PROTOCOL['threshold_grid'] if grid is None else grid
    if not grid or any(not 0 < v <= .1 for v in grid):
        raise ValueError('Threshold grid must stay within (0,0.1]')
    records = [{**screening_counts(labels, probability, eligible, t, alpha / len(grid)),
                'threshold': t} for t in grid]
    allowed = [r for r in records if r['accepted'] and r['upper_risk'] <= risk_limit]
    threshold = max((r['threshold'] for r in allowed), default=None)
    return threshold, records


def acquisition_mask(eligible, probability, known_distance, failure_distance):
    """Cheap research-acquisition screen BEFORE expensive geometry-mass inference."""
    eligible = np.asarray(eligible, bool)
    probability, known_distance, failure_distance = (np.asarray(v, float) for v in
                                                     (probability, known_distance, failure_distance))
    if (eligible.ndim != 1 or not (eligible.shape == probability.shape == known_distance.shape ==
                                  failure_distance.shape) or not np.isfinite(probability).all() or
            np.any((probability < 0) | (probability > 1)) or not np.isfinite(known_distance).all() or
            np.isnan(failure_distance).any() or np.any(known_distance < 0) or np.any(failure_distance < 0)):
        raise ValueError('Invalid acquisition evidence')
    return eligible & (probability <= .1) & (known_distance >= .01) & (failure_distance > .05)


def conformal_radius(scores, alpha=.05):
    scores = np.asarray(scores, float)
    if scores.ndim != 1 or len(scores) == 0 or not np.isfinite(scores).all() or np.any(scores < 0):
        raise ValueError('Invalid conformal calibration residuals')
    if not 0 < alpha < 1:
        raise ValueError('Invalid conformal alpha')
    order = math.ceil((len(scores) + 1) * (1 - alpha))
    if order > len(scores):
        return math.inf  # Finite data do not justify a finite interval at this alpha.
    return float(np.sort(scores)[order - 1])


@dataclass
class DesignDomain:
    x: np.ndarray
    deleted: np.ndarray
    failure_radius: float = .05

    def __post_init__(self):
        self.x = np.asarray(self.x, float)
        self.deleted = np.asarray(self.deleted, int)
        if (self.x.ndim != 2 or self.x.shape[1] != 4 or len(self.x) < 6 or
                self.deleted.shape != (len(self.x),) or not np.isfinite(self.x).all() or
                not np.isin(self.deleted, [0, 1]).all() or self.failure_radius < 0):
            raise ValueError('Invalid domain training data')
        self.low = BOUNDS[:, 0]
        self.span = BOUNDS[:, 1] - self.low
        normalized = (self.x - self.low) / self.span
        self.tree = KDTree(normalized)
        nearest = self.tree.query(normalized, k=2)[0][:, 1]
        self.distance_limit = float(np.quantile(nearest, .95))
        self.scale_distance = max(float(np.median(nearest)), 1.e-8)
        self.hull = ConvexHull(normalized)
        self.failures = KDTree(normalized[self.deleted == 1]) if self.deleted.any() else None

    def evaluate(self, x):
        x = np.atleast_2d(np.asarray(x, float))
        if x.shape[1] != 4 or not np.isfinite(x).all():
            raise ValueError('Nonfinite or malformed proposal')
        normalized = (x - self.low) / self.span
        distance = self.tree.query(normalized)[0]
        failure_distance = self.failures.query(normalized)[0] if self.failures else np.full(len(x), np.inf)
        throat = x[:, 2] - x[:, 3] * np.tan(np.deg2rad(x[:, 0]))
        valid_geometry = ((throat > np.maximum(8 * x[:, 1], .5)) & (x[:, 3] > 8 * x[:, 1]) &
                          (x[:, 2] > 8 * x[:, 1]) & (x >= BOUNDS[:, 0]).all(axis=1) &
                          (x <= BOUNDS[:, 1]).all(axis=1))
        # Chunking in the caller avoids a large pool x hull-facets temporary.
        inside = (normalized @ self.hull.equations[:, :-1].T +
                  self.hull.equations[:, -1]).max(axis=1) <= 1.e-10
        eligible = valid_geometry & inside & (distance <= self.distance_limit) & (
            failure_distance > self.failure_radius)
        return {'eligible': eligible, 'distance': distance, 'failure_distance': failure_distance,
                'interval_scale': 1 + distance / self.scale_distance,
                'valid_geometry': valid_geometry, 'inside_hull': inside}


def regression_metrics(y, prediction, half_width=None):
    from sklearn.metrics import mean_absolute_error, r2_score
    y, prediction = np.asarray(y, float), np.asarray(prediction, float)
    if y.shape != prediction.shape or not len(y) or not np.isfinite([y, prediction]).all():
        raise ValueError('Invalid regression metric inputs')
    error = np.abs(prediction - y)
    positive = y > 1.e-12
    relative = 100 * error[positive] / y[positive]
    result = {'n': len(y), 'mae_J_kg': float(mean_absolute_error(y, prediction)),
              'rmse_J_kg': float(np.sqrt(np.mean(error ** 2))), 'r2': float(r2_score(y, prediction)),
              'bias_J_kg': float(np.mean(prediction - y)), 'max_abs_error_J_kg': float(error.max()),
              'mape_percent': float(np.mean(relative)) if len(relative) else None,
              'ape_q95_percent': float(np.quantile(relative, .95)) if len(relative) else None,
              'relative_metric_excluded_zero_targets': int((~positive).sum())}
    if half_width is not None:
        half_width = np.asarray(half_width, float)
        if half_width.shape != y.shape or np.any(half_width < 0) or np.isnan(half_width).any():
            raise ValueError('Invalid interval widths')
        result.update(coverage=float(np.mean(error <= half_width)),
                      mean_interval_width_J_kg=float(np.mean(2 * half_width)))
    return result


def release_gates(metrics, safety, *, fresh_fea=False, event_finished=False,
                  duration_converged=False, mesh_converged=False, physical_validated=False):
    def within(name, limit):
        value = metrics.get(name)
        return value is not None and math.isfinite(value) and value <= limit
    coverage = metrics.get('coverage')
    gates = {
        'enough_qualification_samples': metrics.get('n', 0) >= PROTOCOL['qualification_min_samples'],
        'mae': within('mae_J_kg', PROTOCOL['qualification_mae_J_kg']),
        'mape': within('mape_percent', PROTOCOL['qualification_mape_percent']),
        'tail_error': within('ape_q95_percent', PROTOCOL['qualification_ape_q95_percent']),
        'interval_coverage': coverage is not None and math.isfinite(coverage) and coverage >= .9,
        'rear_constraint_risk': safety.get('accepted', 0) > 0 and
            math.isfinite(safety.get('upper_risk', math.inf)) and safety['upper_risk'] <= .05,
        'fresh_fea': fresh_fea is True, 'event_finished': event_finished is True,
        'duration_converged': duration_converged is True, 'mesh_converged': mesh_converged is True,
        'physical_validated': physical_validated is True,
    }
    return {'checks': gates, 'passed': all(gates.values()),
            'failed': [name for name, value in gates.items() if not value],
            'status': 'research_only_requires_validation' if not all(gates.values()) else 'validated'}


def regression_candidates():
    from sklearn.compose import TransformedTargetRegressor
    from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import FunctionTransformer, StandardScaler
    from sklearn.svm import SVR

    candidates = {}
    for physics in (False, True):
        prefix = 'geometry' if physics else 'raw'
        transforms = [FunctionTransformer(geometry_features, validate=True)] if physics else []
        for nu in (1.5, 2.5):
            kernel = (ConstantKernel(1., (1.e-3, 1.e3)) *
                      Matern(np.ones(10 if physics else 4), (.01, 100.), nu=nu) +
                      WhiteKernel(.001, (1.e-8, 1.)))
            candidates[f'{prefix}_GPR_Matern{nu}'] = make_pipeline(*transforms, StandardScaler(),
                GaussianProcessRegressor(kernel=kernel, normalize_y=True, alpha=1.e-10,
                                         n_restarts_optimizer=0, random_state=SEED))
        for c in (10., 100.):
            candidates[f'{prefix}_SVR_C{c:g}'] = TransformedTargetRegressor(
                regressor=make_pipeline(*transforms, StandardScaler(), SVR(C=c, epsilon=.05)),
                transformer=StandardScaler())
        for leaf in (1, 3):
            candidates[f'{prefix}_ExtraTrees_leaf{leaf}'] = make_pipeline(*transforms,
                ExtraTreesRegressor(n_estimators=256, min_samples_leaf=leaf,
                                    random_state=SEED, n_jobs=1))
        candidates[f'{prefix}_HistGradientBoosting'] = make_pipeline(*transforms,
            HistGradientBoostingRegressor(max_iter=200, max_leaf_nodes=15, min_samples_leaf=10,
                                          l2_regularization=1., early_stopping=False, random_state=SEED))
    return candidates


def classification_candidates():
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import FunctionTransformer, StandardScaler
    from sklearn.svm import SVC

    candidates = {}
    for physics in (False, True):
        prefix = 'geometry' if physics else 'raw'
        transforms = [FunctionTransformer(geometry_features, validate=True)] if physics else []
        for c in (1., 10., 100.):
            base = make_pipeline(*transforms, StandardScaler(), SVC(C=c, kernel='rbf'))
            candidates[f'{prefix}_SVC_C{c:g}'] = CalibratedClassifierCV(
                base, method='sigmoid', cv=3, ensemble=False)
        base = make_pipeline(*transforms, ExtraTreesClassifier(
            n_estimators=256, min_samples_leaf=3, random_state=SEED, n_jobs=1))
        candidates[f'{prefix}_ExtraTrees'] = CalibratedClassifierCV(base, cv=3, ensemble=False)
        base = make_pipeline(*transforms, HistGradientBoostingClassifier(
            max_iter=150, max_leaf_nodes=7, min_samples_leaf=10, l2_regularization=1.,
            early_stopping=False, random_state=SEED))
        candidates[f'{prefix}_HistGradientBoosting'] = CalibratedClassifierCV(base, cv=3, ensemble=False)
    return candidates

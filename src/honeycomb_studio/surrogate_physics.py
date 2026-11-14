"""Geometry-exact core mass and energy/mass surrogates; no response-derived features."""
import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler

from .campaign_ml import core_mass
from .surrogate_reliability import SEED, geometry_features, regression_candidates


def deterministic_mass(x):
    x = np.atleast_2d(np.asarray(x, float))
    geometry_features(x)  # Reject malformed/nonphysical inputs before network construction.
    masses = np.array([core_mass(tuple(point)) for point in x])
    if not np.isfinite(masses).all() or np.any(masses <= 0):
        raise ValueError('Invalid geometry-derived core mass')
    return masses


def geometry_mass_features(x):
    return np.column_stack((geometry_features(x), deterministic_mass(x)))


class PhysicsEnergyRegressor(RegressorMixin, BaseEstimator):
    """Fit energy=y_SEA*m(x), then predict SEA=energy_hat/m(x).

    m(x) is computed before FEA from the identical clipped-wall network. Observed
    ODB masses are used only to audit this identity, never as prediction inputs.
    The enclosing CV scores the final SEA, so energy rescaling cannot hide errors.
    """

    def __init__(self, estimator):
        self.estimator = estimator

    def fit(self, x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        self.estimator_ = clone(self.estimator).fit(x, y * deterministic_mass(x))
        self.n_features_in_ = x.shape[1]
        return self

    def predict(self, x):
        return self.estimator_.predict(x) / deterministic_mass(x)


def physics_candidates():
    candidates = regression_candidates()
    for name, estimator in list(candidates.items()):
        if '_GPR_' in name:
            candidates['energy_over_exact_mass_' + name] = PhysicsEnergyRegressor(estimator)
    for nu in (1.5, 2.5):
        kernel = (ConstantKernel(1., (1.e-3, 1.e3)) * Matern(np.ones(11), (.01, 100.), nu=nu) +
                  WhiteKernel(.001, (1.e-8, 1.)))
        candidates[f'geometry_exact_mass_GPR_Matern{nu}'] = make_pipeline(
            FunctionTransformer(geometry_mass_features, validate=True), StandardScaler(),
            GaussianProcessRegressor(kernel=kernel, normalize_y=True, alpha=1.e-10,
                                     n_restarts_optimizer=0, random_state=SEED))
    return candidates

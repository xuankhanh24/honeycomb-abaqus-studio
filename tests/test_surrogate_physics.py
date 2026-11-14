import numpy as np
import pytest

pytest.importorskip('sklearn')
from sklearn.base import clone
from sklearn.dummy import DummyRegressor

from honeycomb_studio.surrogate_physics import PhysicsEnergyRegressor, deterministic_mass


def test_geometry_mass_matches_frozen_baseline_without_fea_inputs():
    # Frozen development-0001 at 8 ms. Mass depends only on geometry/density.
    actual = deterministic_mass([[35., .0635, 6.35, 5.]])[0]
    assert actual == pytest.approx(.025853105062479974, rel=1.e-12)


def test_energy_surrogate_scores_and_returns_sea_after_exact_mass_conversion():
    x = np.array([[30., .06, 7., 4.], [30., .09, 7., 4.]])
    mass = deterministic_mass(x)
    sea = 20. / mass
    model = PhysicsEnergyRegressor(DummyRegressor(strategy='mean'))
    trained = clone(model).fit(x, sea)
    np.testing.assert_allclose(trained.predict(x), sea, rtol=1.e-12)
    # The model stores energy, not a mislabeled constant SEA.
    np.testing.assert_allclose(trained.estimator_.predict(x), [20., 20.])


def test_bad_geometry_cannot_generate_a_geometry_mass_feature():
    with pytest.raises(ValueError):
        deterministic_mass([[45., .06, 4.5, 7.]])

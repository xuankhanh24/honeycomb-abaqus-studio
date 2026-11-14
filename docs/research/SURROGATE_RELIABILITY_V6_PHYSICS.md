# v6: geometry-exact mass before FEA

Declared on 2026-11-14 after the v5 exploratory study. V5 did not meet its error
or evidence targets. Keep that negative result. No target or acceptance threshold
is relaxed in this revision.

The existing deterministic `campaign_ml.core_mass` function reproduces all 489
source masses with maximum relative discrepancy below 1e-14. It uses only the four
geometry inputs, the frozen 100-mm panel/core dimensions, density and identical
clipped-wall construction. The actual ODB mass is used to audit this calculation,
never as an ML input at prediction time.

Compare the original 14 v5 candidates with four GPR variants trained on core
energy and divided by geometry-exact mass at prediction, plus two GPR variants
with the geometry-exact mass as an additional deterministic input. All CV scores
are computed for the resulting SEA in J/kg. The complete selection still runs
nested 5x3; scaling and all estimator fitting remain inside training folds.

Use the same original 411 development IDs, 78 historical test IDs and declared
fitting/calibration/qualification split. The latter is now explicitly **exposed
retrospective qualification** following the v5 result, not a fresh holdout.
S1–S5 remain sequential development, grouped together during tuning/calibration.
Choose using fitting CV only. Do not select a model using qualification/test
metrics. Freeze model bytes and FEA predictions before new Actions runs.

All fixed-horizon, binomial, conformal, physical-validation and abstention limits
from the v5 protocol continue to apply. Further reduction of retrospective error
does not establish accuracy on new optimized designs. A separate batch of up to
six newly simulated candidates will assess the frozen final model, after the
existing 12-ms B0249/S5 batch and its bounded resource recovery have finished.

The six new solves run to 12 ms, retaining the original 10-us field and 2-us
history cadence. The worker seals an 8-ms subwindow from `impact_history.csv`
and `rear-field-history.json`, which are already native exports in the verified
8-ms archives. Core energies in this CSV are already in joules. The subwindow
uses a native sample within 100 ns of the target; categorical STATUS-derived
deletion counts are never interpolated. Source byte hashes, sample times and
the 12-ms input hash are retained in `horizon-8ms.json` and the catalog.

The FEA verifier compares the frozen 8-ms predictions only with these 8-ms
labels and reports full 12-ms SEA/damage/event completion separately. Missing
subwindow evidence blocks that comparison while preserving the completed
native solver/archive/restart, without requesting a solver rerun. This validates
the extraction contract in tests; actual dual-horizon native execution is still
pending the new Actions batch.

This tolerance was checked against downloaded, checksum-verified native S5
8-ms histories before dispatch. Abaqus/Explicit places output at increments:
maximum observed scheduling offsets were 59.44 ns (history) and 59.37 ns (field).
The requested target and actual sample/offset are both retained; the tolerance
is 5% of a 2-us history interval and 1% of a 10-us field interval. Larger offsets
are rejected, not silently interpolated. This is an output-timing tolerance,
not an error tolerance for SEA, damage, numerical quality or scientific gates.

Run `scripts/run_reliability_study.py --physics-energy` with a new output directory.

V6.1 also prefilters geometry/support, probability and known-failure distance
before expensive exact-mass evaluation of a candidate pool. This preserves the
acquisition rule and frozen physics. The first v6 run was stopped during this
pool scan after its fitted checkpoints and executed source were retained; v6.1
is a fresh complete run, with unchanged splits, candidate families and gates.

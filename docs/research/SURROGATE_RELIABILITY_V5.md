# Surrogate reliability revision v5

Authorized by the user on 2026-11-14 after S1–S5 verification. This is a new study;
the 489-source archive, v4.1 models and original thesis remain immutable.

## Protocol declared before fitting

The target is **SEA of the core at 8 ms**, at 6.5 m/s. It is not final-event SEA.
Source numerical/archive/history checks remain required. Official ML eligibility
and physical-validation flags are preserved; this exploratory study cannot promote
an incomplete event to an eligible full-event sample. Never mix 8-ms and 12-ms labels.

1. Verify the compact archive checksum and every inventoried member, roles,
   unique inputs, finite values, SEA=core energy/initial mass and evidence flags.
2. Keep the 78 previously exposed historical test samples outside fitting and
   selection. They are a historical diagnostic, never a new blind test.
3. Use nested 5x3 development CV to evaluate the entire regression-selection
   procedure. Feature engineering is deterministic from the four geometry inputs;
   scaling and target scaling are fitted inside each training fold. Compare raw
   and geometry-derived GPR, SVR, Extra Trees and histogram gradient boosting.
4. Freeze a stratified 60/20/20 split of the 411 original development samples
   (seed 20261114): fitting, interval/policy calibration, internal qualification.
   S1–S5 are now exposed sequential-development observations and join fitting
   only, with their true labels. They cannot validate the updated model. Fit and
   tune using fitting data only; qualification is opened after the model and
   threshold are locked. Do not refit the resulting model on held-out data.
5. Calibrate an absolute-residual interval on the calibration split. A deterministic
   distance scale permits wider intervals away from fitting data. Split-conformal
   coverage is marginal under exchangeability; it does not guarantee coverage
   at an optimizer-selected point or physical uncertainty.
6. Select a probability threshold on calibration data from a fixed grid at or
   below 0.10. Require a simultaneous one-sided binomial upper bound <=5% using
   Bonferroni over this grid. If insufficient evidence exists, abstain. Evaluate
   the frozen rule on qualification data and report the separate 95% upper bound.
   These retrospective splits do not replace fresh independent FEA validation.
7. Reject invalid geometry, unsupported designs and configurations at/near known
   fitting failures. A failure-probability estimate never overrides an observed
   failed design. Missing/nonfinite evidence must block acceptance.
8. Optimize the calibrated lower SEA estimate, retain diverse candidates, compare
   against the best observed intact development design as well as B0249, and
   explicitly allow no demonstrated improvement. Every new design needs FEA.

Numerical study targets (project choices, not a published standard): qualification
MAE <=20 J/kg, MAPE <=2%, 95th percentile absolute percentage error <=5%, and
empirical coverage >=90% for a nominal 95% interval. A failed target is reported,
never adjusted after seeing its result. Safety target: deleted fraction among
accepted designs <=5% with a one-sided 95% upper bound on qualification data.

No surrogate output is a validated optimum. Promotion requires fresh FEA,
the rear-element-deletion constraint, numerical quality, duration convergence and
event completion. Mesh/material/experimental validation are additional evidence
requirements. Existing 12-ms B0249/S5 jobs and their recovery retain ownership.

## Primary references

- [scikit-learn: nested CV](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html)
- [scikit-learn: probability calibration](https://scikit-learn.org/stable/modules/calibration.html)
- [SciPy: exact binomial proportion intervals](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html)
- [Conformal prediction, finite-sample assumptions](https://arxiv.org/abs/2107.07511)

Run `scripts/run_reliability_study.py --help` for the standalone reproducible study.
The output directory must be new. All source hashes, split IDs, configuration,
selected estimators, predictions, warnings and failed gates are retained.

# Angle input and batch execution

The re-entrant model accepts either indentation `d` (legacy default for existing
inputs) or angle `reentrant_delta_deg`, selected by `reentrant_geometry`.
Delta is measured from the inclined wall to the vertical Z direction in the XZ
cell section. It is independent of the whole-cell orientation.

`d = reentrant_cell_height / 2 * tan(delta)`; delta is strictly between 0 and 90
degrees. Geometry validation also requires an open waist with sufficient room for
the specified foil. Resolved input, preview geometry, density, CAE builder and
reports all use the derived indentation. Existing indentation-mode inputs remain
valid. The web template defaults to angle entry at 26.56505117707799 degrees,
equivalent to d=1.25 mm at h=5 mm.

## Batch UI

The web's **Chạy đồng loạt theo khoảng** section supports one or more numeric
parameters, start, stop, positive step and an option to add an unaligned end point.
Grid sampling creates every Cartesian combination, with server validation and
duplicate resolved-input removal. Preview displays each selected parameter's
resolved value and unit, including nested material properties. Invalid or inactive
axes remain visible for correction; they are not silently discarded.

Example: delta 20–30 degrees, step 5, and energy 5–7 J, step 2, produces six runs.
The web retains its 10-run cloud limit; the desktop uses the batch max_runs setting.
Desktop has the same angle/indent input modes and sequential/parallel controls
alongside its existing range editor. LHS/table inputs remain available through
advanced input; switching to range mode explicitly clears those designs.

## Scheduling and runtime

`execution_mode` is `sequential` by default or `parallel`. `max_parallel_runs`
limits concurrency to 1–8; CPU per run remains the requested model CPU count.
`ram_per_run_gb` is an explicit admission budget, not measured solver memory.
Admission takes an ordered prefix whose summed CPUs, RAM budgets and predicted
scratch/output disk fit current resources after reserves. Actual RAM/disk reserves
are monitored while jobs run. The web shows a plan against a labelled historical
runner measurement; the worker recalculates at each wave.

On a four-CPU runner, two runs requesting two CPUs each can overlap. Two runs
requesting four CPUs each queue. No requested CPU count, mesh, material, duration,
precision or mass scaling is changed automatically to force concurrency.

Independent native solver processes can overlap. Build/cache/datacheck work is
serialized, preserving geometry-cache reuse across energy sweeps. Arrow,
Matplotlib/reporting and rolling publication remain serialized. A completed wave
is archived before admitting the next wave, avoiding snapshots of live ODBs.
Cloud license failures wait for retry within the existing deadline, with at most
three checkout failures before pause; finished runs are not repeated.

Live owned processes are adopted on engine restart even when no free budget remains
for new launches. Shutdown does not start reserved tasks and preserves owned native
process identity for later adoption. Stop requests terminate owned processes and
retain partial outputs. Resource planning is heuristic, and parallel execution is
not a guarantee of lower wall time for every model.

Production entitlement/runtime/platform gates remain unchanged. This change did
not launch a new native parallel Abaqus study or claim it has been benchmarked.

## Verification and review

Tests cover delta equivalence and invalid geometry, multi-axis expansion, actual
preview geometry, heterogeneous CPU admission, two concurrent test tasks, process
adoption under low free resources, shutdown preservation and cloud license retry
without duplicate records. Synthetic orchestration tests are not research results.
Frontend data tests and TypeScript/build pass; WinUI build and nine C# tests pass.

Standards review found process-adoption and shutdown defects; specification review
found heterogeneous-admission and cloud-license-retry defects. All were fixed with
regression checks. Visual review required resolved preview columns for every axis;
that change was made and verified with delta × core-material modulus on desktop
and mobile. The final independent visual verdict could not run because the reviewer
hit its usage limit; the builder verified the specific fix directly and records
that limitation rather than claiming an independent final pass.

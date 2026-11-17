# V14-03 and CTRL-0245: continue the same analysis to 12 ms

Owner request, 17 November 2026: extend the best verified V14 design and its
repeated control from 8 to 12 ms. The original workflow is 43914437764, physical
source commit `3b40ff65510518e9be6aca9efe53990f86beff82`.

- Only the complete sealed native step-1 end states may be restored. Each has
  eight native state families, four CPUs, double precision and a runtime hash.
- The new deck reads `oldjob`, adds one adiabatic Explicit step of 4 ms and
  preserves output spacing (history 2 µs, field 10 µs). It never reapplies initial
  velocity or starts a new impact. Abaqus native restart datacheck must pass.
- The runtime and six scientific source hashes match the original execution.
  No geometry, material, contact, mass scaling or original quality flags change.
- Each hosted runner stops orderly at 240 minutes from job start, leaving
  90 minutes before its 330-minute hard limit for sealing and publication.
  Four sequential segments automatically recover the previous release's native
  checkpoint. Completed cases skip all subsequent installations and solvers.
- Compare-and-swap claims bind the case, source commit, workflow ID, workflow
  attempt and segment. Duplicate dispatches/reruns fail closed. A solver failure
  retains diagnostics; it never silently switches to a fresh initial solve.
- Checkpoints contain both original and extension jobs, including numbered native
  files. Every restored release volume and whole file is SHA-256 verified.
- The original 4001-row 0–8 ms history is preserved. Before publishing completion,
  compare displacement, velocity and core plastic/damage energies at the boundary;
  reject gaps or incomplete 12 ms histories. The combined history has approximately
  6001 samples; rear STATUS is read over the added step.
- Report SEA, contact force, rear deletion and a separate event-completion
  diagnostic. Twelve milliseconds is an observation window, not proof of full
  event completion or physical validation. The original 411 train rows stay fixed.

Entry: `.github/workflows/continue-v14-12ms.yml`.
State: `cloud-catalog` branch, `catalog/continuation-v14-12ms-20261117/{case}.json`.
Each segment publishes a separate immutable `continue-v14-12ms-20261117-*` release.
The finalizer does not call the general training collector. If all four segments
are exhausted without completion, it reports the checkpoint/failure explicitly;
another recovery requires reviewing that state rather than redispatching from zero.

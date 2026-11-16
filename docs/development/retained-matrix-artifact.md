# Transport a retained matrix ODB without solving

P13-05 from workflow 43808779433 retained an immutable 28 GB Actions artifact,
but no Releases manifest. A saved-solver worker cannot consume that missing
manifest. Downloading it through the local connection is substantially slower
than transferring it between GitHub services.

`recover-matrix-artifact.yml` is a bounded transport workflow. It does not
install Abaqus, connect a license server, build geometry, or invoke a solver.
It pins the original terminal workflow, parent/shard identity, artifact ID,
artifact SHA-256 and original release. It downloads exact byte ranges with the
existing resumable transfer helper and verifies the complete ZIP before exposing
any original files. ZIP paths, links, live-solver locks and disk space are checked.

Only original run/batch/request/runtime metadata, ODB, STA, INP and the solver
completion marker are unpacked. Partial extracted matrices and summaries are
excluded. Original inputs and six physics module hashes must match, and the STA
must confirm a completed solver. The resulting manifest has `complete=false`:
it is transport evidence, not an accepted numerical dataset.

The archive is added to the original shard release under a separate immutable
`checkpoint-actions-<artifact_id>` name. Existing results, tags, manifests and
the original job catalog are not rewritten. Later extraction uses a separate
bounded recovery request and `SavedSolverEngine`, which refuses FE phases.

Tests use synthetic closed-ODB fixtures and verify preserved bytes, exclusion
of incomplete exports/private files, rejection of unsafe/locked ZIP members,
changed inputs/physics, and an unfinished STA. Actual successful transport and
ODB reopening remain runtime verification steps.

```powershell
uv run --locked pytest -q tests/test_matrix_artifact_transport.py tests/test_campaign_artifact_transfer.py tests/test_solver_checkpoint.py
```

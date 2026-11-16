# Recover extraction without repeating a completed solve

For newly launched single-design native cloud shards (research and full profiles), the worker now follows this order:

```text
Build and solve
    -> original STA confirms the requested final time; ODB is closed
    -> upload a bounded, checksummed ODB checkpoint and its immutable manifest
    -> retain the checkpoint reference in the shard catalog
    -> extract, evaluate quality and publish final results
```

This addresses the V11-02 failure mode: a solve completed, but extraction exhausted the runner budget before a usable ODB archive was committed. Previously, the first durable wave checkpoint followed extraction. The new `archiving_solver` phase precedes extraction; an upload failure blocks extraction and preserves the original local attempt for diagnostics. Normal desktop/local processing, smoke jobs and legacy multi-design workers retain their existing behavior.

The checkpoint view includes only the closed design's ODB, original STA/INP, available CAE/model metadata, solver completion marker and portable run/batch manifests. Large binaries are hard-linked in a temporary publication view, not copied on disk. Concurrent runs, extraction arrays, caches and credentials are excluded. Each part and the final manifest are verified by size and SHA-256. Subsequent publication in the same release reuses identical content-addressed parts.

## Recovery behavior

The existing **Recover** action still keeps completed/reviewed, verified sibling shards unchanged. For a failed shard with a valid `solver_checkpoint`, recovery retains its immutable reference as `postprocess_source`. The next worker restores the checkpoint with per-part and whole-file verification, checks the original scientific inputs, runtime and six physics-source hashes, and independently reads the original STA. It queues the original attempt for extraction. `SavedSolverEngine` refuses build, datacheck and solver phases; a bad checkpoint cannot silently fall back to a new FE calculation. A repeated extraction failure retains the same checkpoint reference for the next recovery.

The source code lock and existing main-only/OIDC admission policies remain in effect. Checkpoint transport does not certify numerical or physical quality; those gates run after extraction as before. The archive intentionally remains `complete=false` because its numerical exports have not been produced. The separate checkpoint receipt records a completed solver, not a completed dataset.

This is **ODB postprocessing recovery**, not continuation of an unfinished Explicit analysis. Native restart families are not part of this smaller checkpoint. A recovered output therefore reports `restart_state.available=false` rather than claiming FE restart compatibility. Normal newly solved runs continue to seal their complete native restart state after successful processing.

## Limits and rollout

A checkpoint is recoverable only after its whole ODB and manifest have uploaded successfully. Killing the runner during that first upload can still leave incomplete data; failure/cancellation artifacts remain a secondary fallback. Existing jobs without a verified checkpoint keep the previous selective rerun behavior. Missing/corrupted checkpoint bytes, changed inputs, changed physics sources or a different Abaqus runtime stop recovery for diagnosis.

An already running workflow uses its checked-out source. This change does not retrofit V11-02 workflow `43790215451`, pinned at `ca7adc8894462dcdada717aba424de3f97d9c604`, or reconstruct the incomplete archive from workflow `43730004401`. It must not cancel or duplicate that active solve.

## Regression evidence

```text
uv run --locked pytest -q tests/test_solver_checkpoint.py tests/test_cloud_recovery.py
```

The original Engine failed the two ordering tests: extraction began without a durable-solver callback, and a failed backup did not block extraction. Additional tests exercise split-part publication and restoration, unchanged ODB bytes, exclusion of private files, reuse of the original attempt, rejection of damaged data/runtime/input/source, and explicit refusal of every FE phase. These are transport/orchestration fixtures, not an Abaqus or physical validation claim. Full Linux and Windows CI must pass before merge.

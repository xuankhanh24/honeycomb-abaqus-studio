# Recover a completed ODB from an interrupted legacy extraction

The original P13 worker could finish Abaqus/Explicit and then exhaust its runner
budget while reading full field matrices. Some of those workers retained a
hash-verified, incomplete wave archive containing the closed ODB, native STA,
input deck, run/batch records and runtime lock. The incomplete archive is not an
accepted numerical result.

An explicit `postprocess_source` reference with kind
`honeycomb-archived-solver-postprocess-v1` admits this older archive format. The
manifest asset must match its pinned ID, URL, size and SHA-256. The worker first
restores the original metadata and checks the batch input digest, runtime,
resolved design and six physics module hashes. It then restores only the
original ODB, STA, solver completion marker, input deck and optional geometry
manifest. Every downloaded file and part is verified. Partial extracted fields
and old summaries are not restored.

The STA and completion marker must independently establish solver success. The
original attempt must be closed, native and unlocked. Invalid evidence raises
an error before the recovered run enters the local index. A successful restore
queues the same run and original attempt with `force_new_solver=False` and
`explicit_recover=False`. `SavedSolverEngine` rejects every build, data-check
and solve phase. A recovery cannot silently fall back to a new finite element
solve.

Research postprocessing recovery uses `validation_metrics` at the **original
complete duration**, including a full 8 ms run. It reads native histories, every
rear frame and impactor contact sums. It avoids duplicating full S/U/PEEQ field
matrices, while retaining the evidence used for SEA, Peak Force, rear deletion
and the existing numerical checks. No artificial earlier prediction horizon is
introduced. Input physics, output intervals, material deletion settings and
acceptance flags remain unchanged.

Restore fixtures exercise unchanged split ODB bytes and original-attempt reuse,
as well as rejected corrupted parts, runtime/source changes and an unsuccessful
STA. The recovered result still requires a successful native ODB read, complete
history/STATUS export and the normal numerical quality checks. Software tests
alone are not evidence that a physical design meets its objective.

For a legacy matrix, create a separate bounded recovery request after inspecting
the original workflow state. Pin the original manifest and scientific input;
retain the old workflow and all verified siblings. Do not run ordinary selective
matrix recovery on a legacy shard that has no saved-solver reference, because
that mode may create a fresh solver attempt.

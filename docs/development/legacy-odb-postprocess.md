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

## Admission for an already restored ODB

The first legacy recovery restored a 25 GB ODB, then the common admission
planner still reserved 76.28 GB for a fresh FE dataset plus the 20 GB batch
reserve. The observed runner had 73.4 GiB free and adequate CPU/RAM, so it
rejected extraction before any native reader started.

Only SavedSolverEngine with validation_metrics enabled and full-field export
disabled now uses the closed-ODB scalar budget: 4 GB scratch plus one 1 GiB
publication volume, in addition to the unchanged batch reserve. CPU/RAM gates
remain in force. Normal FE, full-field exports, restart and local admission
policies are unchanged. The no-FE guard and original ODB checksum verification
remain separate requirements. This budget is an orchestration estimate, not
numerical acceptance or physical validation.

The regression test drives the real execute_wave call using the observed
73.4-GiB-free runner and original mesh/output settings. It failed before the
fix; the fixed extraction path is admitted while the identical ordinary FE
path remains blocked. Further cases retain reserve, CPU, RAM and full-export
limits.

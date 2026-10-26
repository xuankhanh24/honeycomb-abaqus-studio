# Honeycomb Abaqus Studio

<!-- impeccable:product-schema 1 -->

## Platform

Windows desktop, x64, WinUI 3, plus a public React/TypeScript web workbench on Vercel.

## Stack

User-selected WinUI 3 and Python. .NET 10 MVVM UI; Python 3.13 local engine; isolated Abaqus 2017 Python 2.7 adapters.

## Users and purpose

Vietnamese engineering researcher building reproducible honeycomb impact simulation datasets for multi-objective design optimization. Primary workflow: inspect every input, preview a study, run it, stop/retry individual runs, inspect results, export and back up.

## Operating context

Local Abaqus/Explicit 2017; reference 7 J model supplied by the user. Sequential execution is the default; optional concurrent solver waves respect requested CPU counts, declared RAM budgets and disk reserves. The Linux development trial used Abaqus 2020 in CentOS 7 userspace on a four-CPU Ubuntu Actions host. Production cloud dispatch remains gated by runtime, entitlement and platform qualification. Runtime estimates are not guarantees.

## Capabilities and constraints

Preserve raw input/results and every attempt. Research exports histories/statistics while retaining original ODB; optional Full exports recorded fields to Parquet with verified rolling publication on the cloud worker. Never label solver completion as physical validation. Keep large simulation data out of Git history; public results reside in GitHub Releases. The public repository belongs to xuankhanh24. Optional Google Drive OAuth backup has verified transfer/restore. Re-entrant geometry accepts indentation or delta angle to vertical, with a validated multi-parameter range editor.

## Product principles

- Trace an exported value to its input, attempt, frame, units and extraction version.
- Show progress measured by the solver, and label estimates.
- Preserve finished work when the study is interrupted.
- Keep numerical settings visible and separate from design variables.

## Accessibility and language

Vietnamese labels and documents, keyboard navigation, system theme, readable contrast, unit-explicit values. Technical file IDs remain ASCII for Abaqus compatibility.

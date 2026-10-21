# Honeycomb Abaqus Studio

<!-- impeccable:product-schema 1 -->

## Platform

Windows desktop, x64, WinUI 3.

## Stack

User-selected WinUI 3 and Python. .NET 10 MVVM UI; Python 3.13 local engine; isolated Abaqus 2017 Python 2.7 adapters.

## Users and purpose

Vietnamese engineering researcher building reproducible honeycomb impact simulation datasets for multi-objective design optimization. Primary workflow: inspect every input, preview a study, run it, stop/retry individual runs, inspect results, export and back up.

## Operating context

Local Abaqus/Explicit 2017; reference 7 J model supplied by the user. One solver at a time, eight CPUs by default, approximately 16 GB RAM. Target solver budget 20–30 minutes is an estimate, not a guaranteed runtime.

## Capabilities and constraints

Preserve raw input/results and every attempt. Export all recorded ODB fields. Never label solver completion as physical validation. Keep large simulation data out of Git. Private GitHub repository owned by xuankhanh24. Optional Google Drive OAuth backup with resumable transfer and verified restore.

## Product principles

- Trace an exported value to its input, attempt, frame, units and extraction version.
- Show progress measured by the solver, and label estimates.
- Preserve finished work when the study is interrupted.
- Keep numerical settings visible and separate from design variables.

## Accessibility and language

Vietnamese labels and documents, keyboard navigation, system theme, readable contrast, unit-explicit values. Technical file IDs remain ASCII for Abaqus compatibility.

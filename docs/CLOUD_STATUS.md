# Cloud implementation: measured status

## Repository and real Ubuntu evidence

The existing repository `xuankhanh24/honeycomb-abaqus-studio` is public. No separate source or data repository was created.

The first real GitHub-hosted Ubuntu audit completed on 25 October 2026:

- [Workflow run 40168384430](https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/40168384430).
- Image: Ubuntu 22.04, `20261023.322.3`, x86-64, glibc 2.35.
- CPU: 4; RAM: 15.61 GiB.
- Disk: 145.19 GiB total, 85.64 GiB available at measurement time.
- Workspace, runner temp and `/mnt` were on the same ext4 root filesystem, not separate disks or RAM filesystems.

Exact byte counts, timestamps and mount evidence are in [environment.json](evidence/cloud-ubuntu-20261025/environment.json). The workflow measures these on every run; it never treats 14 GB as a hard capacity limit or assumes 140 GB is free.

Publication review covered reachable Git blobs and working-tree source using a redacted pattern scan, plus the published Windows ZIP (10,797 entries, checksum matched). Three private-key-header matches were API schema descriptions, with no key payload. This is a bounded review, not proof that every possible credential or distribution issue can be detected.

## Implemented

- `Ubuntu feasibility audit`: manual, no license or installer secrets, no solver invocation. Its green result means hardware observation succeeded, **not** that Abaqus is qualified.
- `Linux engine acceptance`: install from the locked environment and run lint, types and engine/data tests. Tests using fake solvers exercise orchestration only.
- Windows-only marker for `pywin32`, XDG configuration/data defaults on Linux, and a Linux `flock` engine lock. Windows discovery paths remain compatible.
- Existing geometry, output/report and retained-data work is preserved; no running job is migrated or restarted by these changes.
- Credential/activation patterns are excluded from future accidental Git additions.
- Original `.cae`/`.odb` files and the local simulation library were not uploaded as part of the hardware audit.

## Qualification gates — not passed

| Gate | Current status | Required evidence |
|---|---|---|
| Linux runtime | `blocked_environment` | Authorized Linux media, checksum, version-specific installation procedure, measured installation/scratch budget and a real CAE + Explicit smoke run |
| Remote license | `blocked_license` | Authorized license covering the selected Linux solver version, actual CAE/Explicit checkout against the owner's server, manager and vendor-daemon connectivity |
| Full web-submitted workloads | `blocked_platform_policy` | Confirmation that the intended full research workload is eligible under GitHub's Actions terms |

No `runtime-lock.json` certifying a working runtime is generated before those observations exist. No flag or TCP-port check is accepted as proof of a working licensed solver. The current locally installed Windows Abaqus and a running FlexNet server do not establish Linux/cloud entitlement or version compatibility.

The previous Windows cloud draft (`abaqus-cloud.yml`, `setup-abaqus-cloud.ps1`, `run_cloud_study.py`) is archived locally under `output/cloud-windows-draft/`. It is not published as a qualified Ubuntu backend.

## Verified engine acceptance

At revision `c2b50e8`, [Linux engine acceptance](https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/40168769264) passed: **91 tests passed, 1 platform-specific test skipped**, plus Ruff and type checks. The local Windows suite passed all **92 Python tests** and **9 C# tests**; WinUI built with zero warnings/errors. These are software acceptance results, not licensed Linux solver acceptance.

## Next milestone after qualification

Pin the first qualified runtime (2017 preferred for comparison, 2025 or another licensed Linux release allowed), then implement the 330-minute sequential worker, immutable run/attempt manifests, 1-GiB release volumes with SHA-256, resumable postprocessing and bounded Parquet export. Publish settings and history with each job. Drive additionally receives training tables, PDF, job settings and histories; Drive failure must not invalidate the primary GitHub archive.

Only after that gate, build/deploy the Vercel web/API control plane and enable actual cloud dispatch. No Vercel deployment, GitHub App credentials, remote license network, Linux Abaqus installation or cloud simulation is claimed by this milestone. There are currently no configured repository secrets for those services.

Public source and research outputs do not include OAuth tokens, private keys or unverified activation files. See [GitHub Actions terms](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#actions) and [licensing-key distribution restrictions](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies#3-intellectual-property-authenticity-and-private-information).

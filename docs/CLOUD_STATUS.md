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

The owner's requested local license inspection was performed read-only: FlexNet responded, with CAE/Explicit/Standard features reporting 1,024 tokens each and a 31 December 2055 expiry. The activation file contains a SolidSQUAD marker. This is evidence of a functioning local activation setup, not verified publisher authorization or Linux checkout. The internal feature version `70.0` is not an Abaqus release qualification. See the [redacted license audit](evidence/cloud-ubuntu-20261025/license-audit.json); no activation keys, signatures or host IDs were published.

The previous Windows cloud draft (`abaqus-cloud.yml`, `setup-abaqus-cloud.ps1`, `run_cloud_study.py`) is archived locally under `output/cloud-windows-draft/`. It is not published as a qualified Ubuntu backend.

## Verified engine acceptance

At revision `c2b50e8`, [Linux engine acceptance](https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/40168769264) passed: **91 tests passed, 1 platform-specific test skipped**, plus Ruff and type checks. The local Windows suite passed all **92 Python tests** and **9 C# tests**; WinUI built with zero warnings/errors. These are software acceptance results, not licensed Linux solver acceptance.

## Web and pipeline extension (25 October 2026)

Implemented the React/TypeScript workbench, stateless FastAPI preview/API, owner-only write checks, GitHub App catalog/dispatch integration, fail-closed runtime qualification, 330-minute sequential workflow, runtime-aware engine cache, minute-based checks, per-run archival checkpoints and 1-GiB checksum-verified release volumes. Optional Drive readable backup follows primary archival. Software implementation is not native solver acceptance; the actual Linux runtime and checkout remain unqualified; owner credentials are now connected and verified.

The web was deployed via CLI to the new Vercel project `wukong-rom-studio/honeycomb-studio`; production health/template returned HTTP 200. Vercel Git integration could not connect because the authenticated Vercel account lacks repo access. GitHub App/OAuth are now connected, with actual owner login and two draft creations verified. An explicitly approved administrative restart resolved Tailscale NoState; its backend is Running. A real Ubuntu workflow verified private manager/vendor TCP connectivity and blocked negative control ports. No Linux Abaqus install or cloud simulation is claimed. See [CLOUD_WEB.md](CLOUD_WEB.md) for settings, workflows, actual limitations and unfinished acceptance requirements.

Latest acceptance: Windows 112 Python tests and 9 C# tests passed; Ubuntu 111 Python tests passed and 1 platform-specific test was skipped, frontend TypeScript/build passed, lint and Python types passed. This does not replace a licensed Linux smoke or 7-J test. Three existing, completed Windows circular-clamp reference histories are publicly included with provenance and SHA-256, clearly separated from cloud results.

Public source and research outputs do not include OAuth tokens, private keys or unverified activation files. See [GitHub Actions terms](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features#actions) and [licensing-key distribution restrictions](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies#3-intellectual-property-authenticity-and-private-information).


The public deployment is [Honeycomb Studio](https://honeycomb-abaqus-studio.vercel.app). Anonymous production checks verified real JSON responses, preview, 234-wall geometry, all three reference CSV SHA-256 values and denied writes. Evidence: [production checks](evidence/cloud-web-20261025/production-verification.json), [acceptance and blocked native qualification](evidence/cloud-web-20261025/acceptance.json). UI finish review accepted the repaired reference identity, polling, dispatch identity, labels and separate design documentation; owner login and draft writes have since been verified, while solver dispatch/cancellation and native Ubuntu physics remain unverified.

## Owner and private network acceptance

[Workflow 40184261860, attempt 3](https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/40184261860/attempts/3) succeeded. Both FlexNet TCP ports are reachable from an ephemeral Ubuntu runner; 22/445/3389 are blocked. Exact evidence is in [owner/network acceptance](evidence/cloud-web-20261025/owner-and-network-acceptance.json) and [network probe](evidence/cloud-web-20261025/license-network.json). The vendor port was fixed at 27012 without changing signed feature content. OIDC uses the repository immutable identity and main branch, only auth_keys scope, and the restricted runner tag. No activation file or long-lived Tailscale secret was exported.

Native runtime, Linux token checkout and full-workload platform-policy gates remain open. The official software portal requires an entitled account; no such account or authorized Linux installer is currently available. No cloud solver ran, no runtime-lock certification was fabricated, and the research/smoke cases remain drafts.

## Field display and transport extension

At `c77c21a`, the web gained a bounded, sparse field/deformation display for U3, |U|, von Mises and PEEQ. Three actual Windows reference ODBs were read without launching a solver; each display passed 81 independent ODB comparisons at first/middle/final displayed frames. The viewer retains original mesh labels, checks data hashes and shows sampling/missing-value limits. It does not render the full ODB mesh or replace numerical exports.

[Linux acceptance](https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/40192680978) passed 111 tests plus one Windows-only skip; the [web build and three browser-data tests](https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/40192681069) passed. The local Windows Python suite passed 112 tests.

A [real public release roundtrip](https://github.com/xuankhanh24/honeycomb-abaqus-studio/releases/tag/reference-display-20261025) restored seven display/receipt files from thirteen parts with matching SHA-256. Interrupted-download prefix reuse, corrupted content, unsafe paths, incomplete archives and existing-file preservation have software tests. GiB-scale ODB transport and fresh-runner upload recovery remain unaccepted.

Additional primary-source media checks are recorded in [LINUX_MEDIA_FINDINGS.md](LINUX_MEDIA_FINDINGS.md). UCI's AllOS Drive folder requires access not granted to the current account. No request was sent to a third party. Missing native media/checkout, full-workload policy confirmation, cloud Drive connection and the remaining native failure matrix still prevent claiming the entire plan complete.

## Automatic production web deployment

Vercel App installation `175123101` was installed only on the current repository after explicit owner approval. The owner chose to replace the Vercel account's GitHub login connection with `xuankhanh24`; no access was granted to `luukhanh24` on the repository and no collaborator invitation was sent. The existing Vercel project, production environment values and public hostname were retained.

Push `b4a098c` to `main` triggered [a real Git-sourced deployment](https://vercel.com/wukong-rom-studio/honeycomb-studio/ESj7Lkf4RpT6HB3smKhd2jJopRYY), reached READY, and automatically assigned `honeycomb-abaqus-studio.vercel.app`. Production endpoints and all display/reference receipt hashes passed verification. Root directory is `web`; non-production branches are skipped at the project level. Probe `d00589b` on `cloud-data` produced [Canceled by Ignored Build Step](https://vercel.com/wukong-rom-studio/honeycomb-studio/GdDFNKQVjkwnTbkoyoTTm4AMf2S3), with only an operations check file changed and all research jobs retained. See [acceptance evidence](evidence/cloud-web-20261025/git-deployment-acceptance.json). This accepts automatic web deployment, not Abaqus/Linux execution.

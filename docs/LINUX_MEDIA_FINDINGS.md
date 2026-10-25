# Linux installation sources checked — 25 October 2026

A complete third-party 2020 Linux64 media candidate has now been downloaded and inventoried on a real Ubuntu runner. This replaces the earlier finding that no accessible media had been obtained. Publisher authenticity and license entitlement remain unverified; media discovery is not runtime qualification.

## Measured media test

[Inspection run 40198361622](https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/40198361622) succeeded. Its permanent [metadata receipt](evidence/linux-media-inspection-20261025.json) records each volume SHA-256 and exact byte count. The [mirror listing](https://www.softgozar.com/ds-simulia-abaqus_/) supplied five RAR volumes totaling 9801107603 bytes. Only the ISO was extracted: 10,066,642,944 bytes, SHA-256 `d0b227290b5f62ea826b08c18bde222417817fc0d04b91abb0072cb52ebe43ad`.

The ISO contains `4/SIMULIA_EstablishedProducts/Linux64/1/StartTUI.sh`, alongside separate CAE CAA, license-server and Isight installers. The archive's separate activation-tool directory was listed but never extracted or executed. No installation media or activation file was uploaded to GitHub artifacts/cache/releases.

The runner filesystem measured 155,897,610,240 bytes total and 91,939,274,752 bytes free initially; 72,071,540,736 bytes remained after download and ISO extraction. This is measured capacity, not a promised free-space allocation for every runner.

## Repeatable offline installation test

Dispatch `.github/workflows/linux-install-probe.yml`. It builds an Ubuntu 22.04 image from Ubuntu packages, downloads the same media again, verifies the previously observed ISO hash, mounts the ISO read-only and runs the unmodified Established Products installer inside a container with no network, all Linux capabilities dropped and no license or repository credentials passed in. The first-observed hash pins repeatability; it does not establish publisher authenticity.

The driver selects Standard, Explicit, co-simulation, ODB API and CAE, skips installer license configuration and stops on unknown prompts. It then attempts `abaqus information=release` and `abaqus python` importing `odbAccess`. These checks do not consume solver tokens or prove a licensed simulation. Only JSON receipts and installation/command logs are uploaded. A failed test must preserve its actual error; it must not populate an accepted `runtime-lock.json`.

The [original 2020 TUI installation transcript](https://gist.github.com/branfosj/f0bfa2410f7279e5c2d0dfb58bc3c2e6) documents `DSY_Force_OS=linux_a64` and the observed installer menu vocabulary. This selects the installer's existing Linux target; Ubuntu support and runtime library compatibility still require the real tests below.

| Primary source | Observation | Current project consequence |
|---|---|---|
| [Dassault software downloads](https://www.3ds.com/support/software-downloads) | Portal covers software licensed to the account; the opened portal requires login. The user has no entitled download account. | No media obtained. |
| [IIT Kanpur Linux instructions](https://linux.cc.iitk.ac.in/lininfo/Abaqus_2026.html) and [access description](https://linux.cc.iitk.ac.in/lininfo/Abaqus.html) | Instructions link an FTP/HTTP media host; the access description specifies IITK LAN. The host did not resolve from this device. | Cannot use that source from this runner. No institutional license was used. |
| [UC Irvine installation instructions](https://laptops.eng.uci.edu/engineering-software/abaqus-fea-software) | AllOS media includes Linux. Its linked Drive folder was opened in the existing browser account and displayed “Bạn cần có quyền truy cập”. | No installer obtained; no access request was sent and no university activation files were downloaded. |
| [Abaqus 2020/2022 Ubuntu guide](https://github.com/franaudo/abaqus-ubuntu) | Original author documents Ubuntu 20.04 prerequisites and installer detection adjustments. Repository contains instructions, not media. | Candidate compatibility reference; not a recipe validated on our runner/version. |
| [Abaqus 2025 / Ubuntu 24.04 author guide](https://github.com/simfinite-engineering/Abaqus-Installation-Instructions-for-Ubuntu) and [author's explanation](https://www.simfinite.be/blog/simfinite-notes-1/installing-abaqus-2025-on-linux-2) | Author reports newer installer checks and a different OS-detection setting than older CentOS guides. Requires already-present installation folders. | Do not reuse 2017/2022 workarounds blindly for 2025. Native headless installation and library compatibility still require actual media and tests. |

Next technical acceptance remains unchanged: checksum the complete original media, inspect its Linux components and version-specific silent-install mechanism, measure disk use, select compatible runtime libraries, connect to the owner's private FlexNet server, perform real CAE/Explicit checkout, datacheck, solver smoke and ODB reopen. A reachable TCP server does not establish license/version compatibility. Never generate a successful runtime lock from documentation alone.

# Ubuntu runner audit

CPU: 4
RAM: 15.61 GiB

| Path | Total GiB | Free GiB | Filesystem | RAM-backed |
|---|---:|---:|---|---|
| /home/runner/work/honeycomb-abaqus-studio/honeycomb-abaqus-studio | 145.19 | 85.64 | ext4 | False |
| /home/runner/work/_temp | 145.19 | 85.64 | ext4 | False |
| /mnt | 145.19 | 85.64 | ext4 | False |

**Abaqus is not yet qualified. A successful hardware audit is not a successful simulation.**

- `blocked_environment`: No checksum-verified Linux Abaqus runtime has completed qualification.
- `blocked_license`: Linux CAE and Explicit checkout against the owner's server has not been demonstrated.
- `blocked_platform_policy`: Full web-submitted research workloads require confirmed GitHub Actions usage eligibility.

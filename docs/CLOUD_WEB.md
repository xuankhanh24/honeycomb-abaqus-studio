# Web and licensed Linux worker

The public web is a React/TypeScript extension of Honeycomb Studio. Vercel hosts static assets and lightweight FastAPI routes. The service imports shared input contracts and geometry, never Engine, SQLite, Abaqus, pyarrow or a background solver. `scripts/sync_web_service.py` generates its deployable service snapshot; tests compare it with LF-normalized canonical source.

## Actual delivery and remaining setup

The first deployment responds successfully at `/api/health` and `/api/template`. Project: `wukong-rom-studio/honeycomb-studio`. Git integration is not connected: the currently authenticated Vercel account lacks access to the GitHub repository. CLI deployments work; unattended deployment from repo changes is not yet configured.

Public preview, geometry, three actual Windows 7-J reference histories and reduced ODB field displays work without credentials. References use the old circular clamp; they are not cloud acceptance or perimeter-clamp results. The display viewer supports recorded frames, instances, ISO/XY/XZ/YZ projection, displacement scale, U3, displacement magnitude, von Mises and PEEQ. GitHub App login and owner-created catalog writes are connected and verified on production. Two actual drafts exist: a research 7-J perimeter-clamp case and an explicitly separate smoke case. Anonymous writes remain rejected. Solver dispatch stays blocked by native runtime, Linux checkout and platform-policy qualification.

## Vercel settings

Deploy root `web/`, Node 24, Python >=3.13. Build: `npm ci && npm run build`. FastAPI entry: `app.py`; static frontend: generated `dist/`, registered as a literal `app.frontend` directory. CDN promotion is explicitly enabled for public assets; API middleware still protects writes. Do not mount Vercel's reserved `public/` directory. The direction contract remains in emitted HTML. Project deployment SSO is disabled for the requested public site; owner-only API authorization stays active.

Set only encrypted environment values, never public `VITE_` variables:

| Setting | Purpose |
|---|---|
| WEB_SESSION_SECRET | Random signing secret, at least 32 bytes |
| GITHUB_OAUTH_CLIENT_ID / GITHUB_OAUTH_CLIENT_SECRET | GitHub login, callback `<production-url>/auth/callback` |
| GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY / GITHUB_APP_INSTALLATION_ID | App installed only on this repository |
| PLATFORM_POLICY_EVIDENCE_URL | Inspectable confirmation covering intended full workload |

GitHub App repository permissions: Actions write (dispatch/cancel), Contents write (catalog/releases), Checks write (progress). App secrets never go to browsers. Account ID `273490538` alone can control jobs. OAuth state, secure signed cookies and per-session CSRF protect writes. Public POST bodies are limited to 256 KiB; previews resolve at most 10 runs. Geometry complexity is bounded before generating walls.

The API does not treat a URL environment flag as solver acceptance. A validated runtime lock is required next to the service module. Keep it identical to the worker root `runtime-lock.json`; copy only after qualification and peer inspection. Required evidence includes release/Python, installer SHA-256, image identity/digest, successful Linux solver receipt, reopened ODB, and CAE/Explicit checkout evidence URLs. No qualified runtime exists yet.

## Runner setup

| Secret or variable | Purpose |
|---|---|
| ABAQUS_LINUX_BUNDLE_URL (secret) | Authorized HTTPS Linux installation bundle including version-specific `install.sh` |
| ABAQUS_LINUX_BUNDLE_SHA256 (variable) | SHA-256 of complete bundle |
| ABAQUS_DISK_BUDGET_JSON (variable) | Measured byte budgets: download, extracted, installed, scratch, odb, export, upload, reserve |
| ABAQUS_LICENSE_ENDPOINT (secret) | `manager-port@private-host` |
| ABAQUS_VENDOR_PORT (secret) | Fixed vendor daemon port, verified on license server |
| TS_OAUTH_CLIENT_ID / TS_AUDIENCE (secrets) | OIDC client identifier and audience; tag `honeycomb-runner`, no stored Tailscale OAuth secret |
| HONEYCOMB_DRIVE_CREDENTIALS_JSON (optional secret) | Authorized Google OAuth credential, drive.file scope |

Keep the actual activation file on the Windows license server. Do not copy it to GitHub cache, repository, artifacts or Vercel. Tailscale is now Running after an explicitly approved administrative service restart. FlexNet manager uses TCP 27011; the vendor port is fixed to 27012. The license service was restarted only after confirming no tokens were in use; comparison with the private backup confirms every byte outside the vendor configuration line is unchanged. No Windows firewall rule, public tunnel or router forwarding was added.

The saved Tailscale policy grants `tag:honeycomb-runner` access only to those two TCP ports on the license host and includes deny tests for 22/445/3389. A successful real Ubuntu run verified both positive connections and the three blocked negative controls. The ephemeral runner was removed after logout. See [network receipt](evidence/cloud-web-20261025/license-network.json) and [workflow attempt 3](https://github.com/xuankhanh24/honeycomb-abaqus-studio/actions/runs/40184261860/attempts/3). This proves TCP reachability, **not** Linux CAE/Explicit checkout, entitlement, or solver execution.

### OIDC subject binding

The federated identity has only `auth_keys` scope, restricted to `tag:honeycomb-runner`, with issuer `https://token.actions.githubusercontent.com`. Query the repository's actual OIDC configuration before constructing its subject:

```shell
gh api repos/xuankhanh24/honeycomb-abaqus-studio/actions/oidc/customization/sub
```

This repository uses immutable subjects. Its accepted subject is `repo:xuankhanh24@273490538/honeycomb-abaqus-studio@1427757326:ref:refs/heads/main`. The older name-only format was rejected by Tailscale. The successful run followed an exact subject correction, preserving all scope, tag and network restrictions. All three Linux workflows use `id-token: write`, the generated audience and `tailscale/github-action@v4`; no long-lived Tailscale secret is copied to GitHub.

### Linux media still unavailable

The [official download portal](https://www.3ds.com/support/software-downloads) was opened and requires a 3DEXPERIENCE login with access to the licensed media. No authorized Linux media or entitled portal session is available. The user reports not having an account entitled to download it. Existing Windows activation metadata and successful TCP probes cannot replace a Linux installer or establish Linux checkout. No qualified runtime lock is generated and no real cloud solver job has been started.

`Qualify native Abaqus Linux environment` is the first real solver workflow, independent of the full research gate. It requires genuine media/network settings, runs a tiny CAE model, datacheck, Explicit and ODB reopen, and records only observed results. It does not manufacture `runtime-lock.json` or assume success when inputs are absent. The probe adapter has not been executed in Abaqus Linux yet.

`Licensed Linux research run` accepts only an existing owner-created catalog ID on main. It serializes solvers, limits batches to 10 runs and jobs to 330 minutes, reserves time for archival, pins the accepted runtime, and has no fake/local fallback. Smoke is an explicitly shortened environment probe, not a full research case. Research preserves 6-ms input physics unless the user explicitly supplied another model.

## Archives and limitations

Each run retains requested/resolved settings and history. Engine cache includes runtime and adapter hashes. Checks carry current phase about once per minute; the catalog changes at stage transitions. Completed runs are uploaded before starting the next. Data files are split into at most 1-GiB content-addressed parts and uploaded without creating a duplicate ZIP. Release digests and sizes must match before the final completeness manifest is published. Retry reuses matching uploaded parts; an unmatched part fails verification. Original ODBs are never deleted automatically.

Drive readable backup happens after the verified GitHub archive; failure is recorded separately. Credential refresh stays in memory. Private credentials and resumable-upload manifests are excluded from public archives. Drive cloud backup is implemented but not connected or end-to-end tested. Existing readable exports include tables, reports and settings/history through the shared retained-data pipeline.

Not yet accepted: real Linux 7-J comparison, interrupted large upload recovery across fresh runners, long-run cancellation/timeout preservation, full-resolution ODB web rendering, native solver restart across runners, and complete cloud failure-injection matrix. An interrupted active ODB cannot be guaranteed durable if Actions kills the process before upload; completed run checkpoints reduce but do not eliminate that risk. Current code uploads incrementally after runs; it does not yet evict all exported Parquet incrementally during extraction.

Release manifests are the durable source of truth. Short-lived Actions diagnostic artifacts are supplementary only. No successful Linux research job, license compatibility or platform-policy approval is claimed.

## Field display and archive restore acceptance

`adapters/viewer.py` opens ODB read-only using Abaqus Python 2.7/3, with a default budget of 1,000 shell elements and 13 frames. It preserves original connectivity, labels and nodal coordinates; display field values use eight significant digits. Missing field values stay null. U contours show the mean of the displayed element's nodal values; stress/PEEQ show maximum recorded integration/section point values without nodal extrapolation. Unsupported element types are inventoried, not silently reinterpreted. Units follow the mm-N-s model contract; ODB does not identify physical units itself. Original ODB and full numerical exports are unchanged.

The three public reference displays were extracted from completed Windows ODBs. Each passed 81 independent ODB comparisons at the first/middle/final displayed frames (coordinates, U and element maxima); this is extraction acceptance, not physical or Linux acceptance. Their JSON, ODB hashes and cross-check receipts are under `web/static/reference/`. Rendering is a sparse element sample, not a complete surface or full ODB viewer. The browser verifies SHA-256, units, connectivity, frame lengths and bounded sizes before rendering; imported JSON is processed locally. Canvas has a textual range and a table of sampled element labels/values. Display extremes are explicitly not full-ODB extrema.

Future qualified cloud runs retain `extracted/field-view.json`. The worker uploads a separate display asset when it fits 4 MiB; a catalog-bound API verifies its size and SHA-256 before serving it. The client cannot choose upstream URLs or asset IDs. Large numerical results still download directly from Releases. A display convenience-upload failure does not invalidate the primary numerical archive.

Download a release's `*-artifact-manifest.json`, then reconstruct its files with:

```shell
uv run python scripts/restore_cloud_archive.py artifact-manifest.json restored-results
```

The restorer streams each part, validates its size/SHA-256, verifies the reconstructed file and publishes it only afterward. On another invocation, completed partial-file segments are rechecked and reused. Different existing files, unsafe paths, symlinks, foreign repository URLs and malformed part inventories are rejected. Incomplete checkpoints require explicit `--allow-incomplete` and remain marked incomplete. No solver is launched.

A real [public release roundtrip](https://github.com/xuankhanh24/honeycomb-abaqus-studio/releases/tag/reference-display-20261025) uploaded and restored 7 display/receipt files in 13 one-MiB parts, with all file hashes verified. This deliberately small multipart test does not certify GiB-scale ODB transfer, fresh-runner upload recovery, or native ODB reopening. [Receipt](evidence/cloud-web-20261025/release-display-roundtrip.json).

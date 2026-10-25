# Web and licensed Linux worker

The public web is a React/TypeScript extension of Honeycomb Studio. Vercel hosts static assets and lightweight FastAPI routes. The service imports shared input contracts and geometry, never Engine, SQLite, Abaqus, pyarrow or a background solver. `scripts/sync_web_service.py` generates its deployable service snapshot; tests compare it byte-for-byte with canonical source.

## Actual delivery and remaining setup

The first deployment responds successfully at `/api/health` and `/api/template`. Project: `wukong-rom-studio/honeycomb-studio`. Git integration is not connected: the currently authenticated Vercel account lacks access to the GitHub repository. CLI deployments work; unattended deployment from repo changes is not yet configured.

Public preview, geometry and the three actual Windows 7-J reference histories work without credentials. References use the old circular clamp; they are not cloud acceptance or perimeter-clamp results. The web is not yet an ODB field/deformation viewer. Owner login and dispatch need the service credentials below; until then the service rejects writes.

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
| TS_OAUTH_CLIENT_ID / TS_OAUTH_SECRET (secrets) | Ephemeral runner network identity, tag `honeycomb-runner` |
| HONEYCOMB_DRIVE_CREDENTIALS_JSON (optional secret) | Authorized Google OAuth credential, drive.file scope |

Keep the actual activation file on the Windows license server. Do not copy it to GitHub cache, repository, artifacts or Vercel. Tailscale ACLs should allow runner access to only license manager and vendor ports; do not enable a public tunnel or router port forwarding. Browser login was completed, but Windows currently reports `NoState` and service restart was denied by Windows permissions. A connected private network is not yet established. No Tailscale runner OAuth credential or vendor fixed-port configuration has been created.

`Qualify native Abaqus Linux environment` is the first real solver workflow, independent of the full research gate. It requires genuine media/network settings, runs a tiny CAE model, datacheck, Explicit and ODB reopen, and records only observed results. It does not manufacture `runtime-lock.json` or assume success when inputs are absent. The probe adapter has not been executed in Abaqus Linux yet.

`Licensed Linux research run` accepts only an existing owner-created catalog ID on main. It serializes solvers, limits batches to 10 runs and jobs to 330 minutes, reserves time for archival, pins the accepted runtime, and has no fake/local fallback. Smoke is an explicitly shortened environment probe, not a full research case. Research preserves 6-ms input physics unless the user explicitly supplied another model.

## Archives and limitations

Each run retains requested/resolved settings and history. Engine cache includes runtime and adapter hashes. Checks carry current phase about once per minute; the catalog changes at stage transitions. Completed runs are uploaded before starting the next. Data files are split into at most 1-GiB content-addressed parts and uploaded without creating a duplicate ZIP. Release digests and sizes must match before the final completeness manifest is published. Retry reuses matching uploaded parts; an unmatched part fails verification. Original ODBs are never deleted automatically.

Drive readable backup happens after the verified GitHub archive; failure is recorded separately. Credential refresh stays in memory. Private credentials and resumable-upload manifests are excluded from public archives. Drive cloud backup is implemented but not connected or end-to-end tested. Existing readable exports include tables, reports and settings/history through the shared retained-data pipeline.

Not yet accepted: real Linux 7-J comparison, interrupted large upload recovery across fresh runners, long-run cancellation/timeout preservation, full field web viewer, native solver restart across runners, and complete cloud failure-injection matrix. An interrupted active ODB cannot be guaranteed durable if Actions kills the process before upload; completed run checkpoints reduce but do not eliminate that risk. Current code uploads incrementally after runs; it does not yet evict all exported Parquet incrementally during extraction.

Release manifests are the durable source of truth. Short-lived Actions diagnostic artifacts are supplementary only. No successful Linux research job, license compatibility or platform-policy approval is claimed.

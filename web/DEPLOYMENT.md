# Production web deployment

Use the existing project `wukong-rom-studio/honeycomb-studio`, with the GitHub login connection `xuankhanh24` and only the repository `xuankhanh24/honeycomb-abaqus-studio` enabled in the Vercel GitHub App.

- Production branch: `main`.
- Project root directory: `web`.
- Framework: FastAPI; Node 24; build command `npm ci && npm run build`.
- Public project domain: `honeycomb-abaqus-studio.vercel.app` (verified, production assignment).
- Ignored Build Step: **Only build production**. The `cloud-data` catalog branch is not an application deployment branch.
- Encrypted production environment values remain on the existing project. No credentials belong in source or public build variables.

Push changes to `main`, inspect the Vercel commit check, and verify the new production deployment's commit SHA, readiness, domain assignment, `/api/health`, `/api/template`, `/api/session` and public reference hashes. A successful web deployment does not qualify an Abaqus Linux runtime or start a solver.

For an explicitly needed CLI deployment, run from the **repository root**, with its ignored local `.vercel/project.json` linked to the same project. The server-side root directory is already `web`; do not upload only the subdirectory as though the root setting were empty.

```shell
vercel link --project honeycomb-studio --scope wukong-rom-studio
vercel deploy --prod --scope wukong-rom-studio
```

Public evidence and unfinished native acceptance remain in [CLOUD_WEB.md](../docs/CLOUD_WEB.md) and [CLOUD_STATUS.md](../docs/CLOUD_STATUS.md).

## Production regression checks on GitHub Actions

`Production web regression acceptance` runs after a successful `Cloud web acceptance` on main, or manually with an exact `expected_sha`. It waits for `/api/health.revision` to match that commit before testing the public production API and a real Chromium session. The revision is the public `VERCEL_GIT_COMMIT_SHA`; local instances return null.

The workflow verifies table-mode validation, exact 5/7/9 J previews, geometry, mobile preview, the real saved-job catalog/detail, existing results and asset hashes, plus denied anonymous writes. It also runs the three fixes' regression tests and engine smoke contract on Ubuntu. No catalog responses are mocked; the workflow does not authenticate an owner, dispatch a solver or change saved jobs. Its screenshots, JSON receipt and JUnit results are retained in the run's `production-web-review-*` artifact.

```shell
gh workflow run production-web.yml --ref main -f expected_sha=<full-deployed-commit-sha>
```

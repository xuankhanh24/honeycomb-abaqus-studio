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

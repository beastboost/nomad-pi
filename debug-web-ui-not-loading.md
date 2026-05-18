# Debug Session: web-ui-not-loading

- Status: OPEN
- Date: 2026-05-17
- Scope: Local runtime verification of current `nomad-pi` web UI loading behavior

## User Symptom

- On the Radxa A7Z, after setup/update attempts, the web UI refuses to load.
- Locally, the app had previously loaded, but the user wants the current state re-tested.

## Constraints

- No business-logic changes before runtime evidence is collected.
- Use this file to track hypotheses, evidence, and next actions.

## Initial Hypotheses

1. The backend process starts locally, but the root route or static asset serving now fails at runtime.
2. The root HTML loads, but one or more required static assets (`css`, `js`, fonts, manifest) fail and make the UI appear broken.
3. Authentication or first-run setup logic is now preventing the app shell from rendering correctly after the initial HTML response.
4. A recent UI/CSS/HTML change introduced a client-side error that prevents the app from initializing after page load.
5. The issue on the Radxa is environment-specific, while the current local state may still work, so we need a fresh local control test before comparing environments.

## Plan

1. Reproduce locally against the current branch state.
2. Verify root HTML, key static assets, and login endpoint behavior.
3. Inspect current runtime logs for server-side errors.
4. Only if evidence shows a real local regression, instrument or fix minimally.

## Evidence

- Local root request to `http://127.0.0.1:8000/` returned `200` and served the HTML document.
- Exact referenced static assets returned `200` locally:
  - `/css/style.css?v=1779051600`
  - `/js/app.js?v=1775509265`
  - `/manifest.json`
  - `/icons/icon-512.svg`
- Real auth/init endpoints returned `200` locally:
  - `/api/auth/login`
  - `/api/auth/check`
  - `/api/auth/me`
- `/api/auth/status` returned `404`, but frontend inspection shows the app uses `/api/auth/check`, so that endpoint is not part of the active startup flow.
- Local `data/app.log` shows normal startup messages and no server-side error corresponding to a UI load failure.

## Hypothesis Status

1. The backend process starts locally, but the root route or static asset serving now fails at runtime.
   - Rejected locally by `200` responses from `/` and the required static assets.
2. The root HTML loads, but one or more required static assets fail and make the UI appear broken.
   - Rejected locally by direct `200` responses from the exact referenced CSS/JS asset URLs.
3. Authentication or first-run setup logic is now preventing the app shell from rendering correctly after the initial HTML response.
   - Rejected locally by successful `/api/auth/login`, `/api/auth/check`, and `/api/auth/me` responses.
4. A recent UI/CSS/HTML change introduced a client-side error that prevents the app from initializing after page load.
   - Not reproduced locally from server-side evidence; still possible on Radxa if browser cache or deployment state differs.
5. The issue on the Radxa is environment-specific, while the current local state may still work, so we need a fresh local control test before comparing environments.
   - Currently the strongest surviving hypothesis.

## Current Conclusion

- The current branch does load locally in its present state.
- The reported failure is not reproduced on this machine from the current source tree and running app.
- The next debugging target should be Radxa-specific deployment/runtime differences: stale files, wrong branch/revision, reverse proxy/network binding, cached browser assets, or service startup failure on the device.

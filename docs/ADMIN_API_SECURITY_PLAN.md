# Blue Bot Admin Dashboard — Secure Integration Plan

## Current state

The `admin/` dashboard is a static design prototype. Its displayed metrics and activity are illustrative, and it must remain explicitly labelled as preview data until live integration is implemented. The existing production process is `python3 bot.py`; that process owns the Telegram webhook at `/webhook` and the existing health endpoints.

## Non-negotiable invariants

- Do not change Telegram command names, callback identifiers, keyboard labels, referral flows, video/photo delivery, rating counters, or owner checks as part of dashboard work.
- Preserve MongoDB database `BlueBotDB`, collections `users`, `videos`, and `settings`, their document keys, and current update semantics.
- Preserve `POST /webhook`, `GET /`, `HEAD /`, `PORT`, `WEBHOOK_URL`, `RENDER_EXTERNAL_URL`, and the Render start command.
- Never expose `BOT_TOKEN`, `MONGO_URI`, owner IDs, database documents, or exception tracebacks to the browser.
- Do not merge or deploy the dashboard until authentication, authorization, regression checks, and deployment behavior have been validated.

## Proposed implementation sequence

### 1. Authentication and authorization first

- Add a dedicated dashboard password/secret configuration through Render environment variables; never hard-code secrets.
- Fail closed: dashboard API requests must be denied when required auth configuration is absent or invalid.
- Use server-validated sessions with signed, time-limited cookies marked `HttpOnly`, `SameSite=Strict`, and `Secure` when served over HTTPS. Do not place credentials or session secrets in browser local storage.
- Verify authorization on every protected server request, not just by hiding UI controls.
- Add login throttling and generic failure responses; never log submitted credentials.
- Keep all dashboard operations read-only in the first live integration phase. No broadcast, delete, configuration-write, or user-mutation endpoints.

### 2. Read-only metrics API

Expose only aggregated, allow-listed values needed by the Overview:
- user count from the existing users collection;
- media counts grouped by supported media type;
- request/view counters only where the existing schema provides reliable values;
- health/readiness state without returning connection strings or raw exceptions.

Use bounded queries and explicit response schemas. Treat missing fields and database failures safely. Do not invent historical analytics when the database does not store time-series events; show “Not available” rather than fabricated charts. Do not return raw user lists or media documents in this phase.

### 3. HTTP integration without breaking the bot

- Extend the existing HTTP handler deliberately or introduce a separately reviewed server arrangement; do not accidentally replace the Telegram webhook server.
- Route matching must be exact. Unknown paths return 404; unauthorized API calls return 401/403 with no sensitive details.
- Serve the dashboard only after the authentication behavior is designed and tested. Keep the static preview clearly marked until it consumes authenticated, real responses.
- Preserve webhook response behavior and startup/shutdown semantics.

### 4. Regression and security tests

Required before merge:
- existing static UI contract tests and Python/JavaScript syntax checks;
- route tests for the existing root, HEAD, webhook, unknown paths, and malformed request bodies;
- authentication tests for missing, invalid, expired, and valid sessions;
- authorization tests proving every protected endpoint denies anonymous access;
- API tests proving only allow-listed aggregate fields are returned;
- failure tests for unavailable MongoDB and absent auth environment variables;
- a check that secrets and raw database documents never appear in API responses;
- review of dashboard HTML/JS for safe DOM updates and no credential persistence.

### 5. Release gate

Keep the work on `redesign/premium-dark-safe-ui` until all automated checks pass and the owner has reviewed the result. Deploy only after Render environment variables and HTTPS behavior are verified. Then verify the existing Telegram webhook and health endpoint before declaring completion.

## Explicitly out of scope for the first live phase

- Dashboard-triggered broadcasts or destructive actions.
- Editing bot settings or user permissions from the web.
- User-level personal data tables.
- Analytics that require event history not currently stored.
- Changes to Telegram business logic or MongoDB schema.

## Implemented first integration slice

- Added `admin_dashboard.py`, an isolated route handler invoked before the existing root/webhook handlers. Existing `GET /`, `HEAD /`, and `POST /webhook` paths retain their prior code paths.
- Dashboard routes fail closed with HTTP 503 unless `ADMIN_DASHBOARD_PASSWORD` is 6–16 characters and `ADMIN_SESSION_SECRET` is 6–20 characters. This is the requested compatibility policy; short passwords and especially short session secrets materially weaken production security. Prefer a long, randomly generated session secret for a production deployment.
- `GET /admin/login` provides a password form. Successful login issues a signed, eight-hour session cookie with `HttpOnly`, `Secure`, and `SameSite=Strict` attributes. Invalid logins are throttled per client address in-process. A POST-only `/admin/logout` endpoint expires the session cookie; the dashboard provides a Sign out control.
- `/admin`, its CSS/JS assets, and `GET /admin/api/overview` require a valid session. The API returns only aggregate counts and does not expose user documents, identifiers, tokens, or media records.
- The API intentionally reports request analytics as unavailable because the current database schema does not establish a reliable daily request count. The dashboard updates live user/media totals after authenticated login; the chart remains labelled as illustrative.
- Added session-token, configuration-boundary, fail-closed, anonymous API denial, authenticated aggregate response allow-list, login-form length, valid login cookie issuance, failed-login throttling, and POST-only logout contract tests. The test suite uses fake handlers and mocked collections; it does not connect to Telegram or a live MongoDB instance.
- Replaced fabricated initial user/media totals and percentage trends with neutral loading placeholders so database/API failure cannot leave demo numbers looking like production data.
- Before enabling this feature on Render, set both environment variables in the service Environment settings. The configured policy accepts a 6–16 character dashboard password and a 6–20 character session secret, but this short secret policy is not recommended for production because it weakens session-cookie integrity. Use HTTPS only. Keep credentials out of source control and logs.

## Remaining release gates

- Confirm GitHub Actions passes on the current branch.
- Exercise a complete browser login/logout lifecycle, session expiry, login rate limiting, and API behavior against a test server/database. Unit-level tests currently cover token validation, fail-closed configuration, anonymous denial, and aggregate response fields.
- Verify Render proxy/TLS behavior and the Telegram webhook after deployment.
- No live Render deployment has been performed by this change.

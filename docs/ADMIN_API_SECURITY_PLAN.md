# Blue Bot Telegram Mini App — Security and Release Plan

## Current implementation

The owner dashboard is a Telegram Mini App served by the existing Python webhook process at `/admin/`. It is not a standalone browser login dashboard. The Mini App loads Telegram's Web App SDK and sends `Telegram.WebApp.initData` to `POST /admin/api/overview`.

The server verifies Telegram's HMAC signature using `BOT_TOKEN`, validates the signed `auth_date`, and authorizes the numeric Telegram user ID against `OWNER_IDS` (with `OWNER_ID` as a legacy fallback). Invalid, expired, duplicate-parameter, tampered, or non-owner init data is rejected. The API is read-only. The overview endpoint returns aggregate counts; the user directory endpoint returns a paginated, searchable allowlist of user ID, username, first name, share count, and ban status; the media endpoint returns paginated media metadata without Telegram file IDs; and the settings endpoint returns safe configuration status only, without raw group IDs or private-access user IDs. A user-detail endpoint accepts one numeric Telegram user ID and returns an explicit allowlist of profile, shares/referrals, ban status, workflow state, and joined-at display fields when stored; older records may not contain referral or joined-at fields, so the UI uses safe fallbacks.

The owner Mini App is launched by the owner-specific Telegram menu button and the owner-only **Admin Panel** button in the `/start` welcome message. Ordinary users retain the existing welcome keyboard and default Telegram Commands menu. A normal browser shows an instruction to open the Mini App in Telegram and cannot retrieve overview data without valid owner-authenticated init data.

## Non-negotiable behavior invariants

- Do not change existing command names, callback identifiers, referral flows, gender/channel gates, media delivery, rating counters, or owner checks beyond additive presentation-only changes.
- Preserve MongoDB database `BlueBotDB`, collections `users`, `videos`, and `settings`, their document keys, and existing write/update semantics.
- Preserve `POST /webhook`, `GET /`, `HEAD /`, `PORT`, `WEBHOOK_URL`, `RENDER_EXTERNAL_URL`, and the Render start command `python3 bot.py`.
- Never expose `BOT_TOKEN`, `MONGO_URI`, owner lists, database documents, media file IDs, or exception tracebacks to the Mini App.
- Do not merge or deploy to production until automated checks and owner/non-owner Telegram tests are complete.

## Authentication and authorization

- Telegram `initData` is validated server-side; never trust `initDataUnsafe` as an authorization source.
- Reject invalid HMACs, stale or future timestamps outside the allowed clock tolerance, duplicate query parameters, malformed JSON, missing tokens, and IDs not in `OWNER_IDS`.
- Keep all overview data behind `POST /admin/api/overview`. The static HTML/CSS/JS assets contain no secrets or private database content.
- The API returns only the allow-listed aggregate response: owner display identity, total users, media, videos, photos, status, and `requests_today: null` because reliable daily request history is not stored.
- The API limits request bodies, uses no-store response caching, sets security headers, and returns a generic 503 when aggregate queries fail.
- Keep the dashboard read-only in this phase. User and media directory search must use escaped literal search terms, bounded pagination, field projections, and explicit response allowlists. The user-detail endpoint must look up exactly one numeric Telegram ID, return only its explicit allowlist, and return generic errors without database details. Never return Telegram media file IDs. Do not add broadcast, delete, configuration-write, or user-mutation endpoints.

## Metrics definitions

- Users: count of documents in the existing `users` collection.
- Videos: count of existing `videos` documents whose IDs match `vN` or `zN`.
- Photos: count of documents with `type: "photo_only"` (including public `pN` and private `zpN` IDs).
- Media: videos plus photo-only documents.
- Daily request analytics: unavailable until the application stores a reliable time-based event history. Do not display fabricated values.

## Automated validation

The GitHub Actions workflow `.github/workflows/validate.yml` runs Python compilation, the unittest suite, and JavaScript syntax validation. Tests cover Telegram init-data verification, owner authorization, stale/future/tampered data, duplicate parameters, method restrictions, aggregate response allow-listing, database failures, oversized bodies, UI behavior contracts, and HTTPS Mini App URL resolution.

The regression suite also covers malformed stored metadata (strict private flags, non-negative integer counters, and safe broadcast-flag fallback), oversized numeric ID searches and user IDs outside BSON signed-64-bit range, strict pagination types, bounded Telegram initData field parsing, HTTP handler integration with the existing webhook/health paths, and stale responses across all Mini App section-navigation routes. CI explicitly compiles both `bot.py` and `admin_dashboard.py`, runs the unittest suite, and checks JavaScript syntax. These automated tests use fake request handlers and mocked collections. They do not establish live Telegram Bot API behavior, production MongoDB correctness, or Render deployment health.

## Release gates before merge

1. Confirm the latest CI run passes on the exact PR head commit.
2. Verify Render's service branch and deployment configuration without changing the production service during review.
3. Confirm the HTTPS Mini App URL resolves to `/admin/` and the API returns expected responses in a controlled environment.
4. Test in Telegram with an account listed in `OWNER_IDS`: the owner-only menu button and `/start` Admin Panel button must open the Mini App, and aggregate metrics must load.
5. Test with a non-owner: the Admin Panel button must not appear and all overview, user, user-detail, media, and settings API routes must deny access.
6. In the owner Mini App, search users by name, username, and exact ID; open User Detail; verify optional legacy fields show a safe fallback when absent; return to the list and then Overview without stale panels or hidden controls.
7. In Media Library, verify all/video/photo filters, pagination and search; confirm the browser response contains no Telegram `file_id`, `video_ids`, or `photo_ids` values.
8. In Bot Settings, verify only status/count values appear; confirm no raw channel/group IDs or private-access user IDs are exposed. Confirm all management views remain read-only.
9. Verify existing `/start`, referral, channel/gender gates, video/photo lookup, and webhook behavior remain intact.
10. Only after these gates pass, review and merge the PR; production deployment requires a separate explicit go-ahead.

## Current limitations

- User Management supports searchable/paginated records and a read-only user detail view. Media Library supports searchable/paginated metadata and type filters. Bot Settings shows configuration status only; none of these views can mutate bot state.
- No live Render deployment, production MongoDB test, or live owner/non-owner Telegram integration test has been completed for this branch.
- The production Render service currently tracks `main`; this PR branch is intentionally not deployed before the release gates pass.

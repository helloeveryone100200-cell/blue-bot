# Blue Bot Redesign — Baseline & Behavior Audit

## Scope
- Repository: `helloeveryone100200-cell/blue-bot`
- Baseline branch: `main`
- Implementation branch: `redesign/premium-dark-safe-ui`
- Design direction: Premium Dark (Deep Navy + Indigo)
- Initial bot UI scope: Telegram welcome-message presentation only; a separate static dashboard prototype was added afterward.

## Baseline architecture observed
- Main application: `bot.py` (2,657 lines in the inspected baseline).
- Telegram framework: `pyTelegramBotAPI` / `telebot`.
- Database: MongoDB, database `BlueBotDB`, collections `users`, `videos`, `settings`.
- HTTP server and Telegram webhook are implemented in `bot.py`.
- Render start command in `render.yaml`: `python3 bot.py`.
- Dependencies are pinned in `requirements.txt`.

## Existing command handlers observed
`/start`, `/autobroadcast`, `/ref`, `/setchannel`, `/removechannel`, `/contact_to_owner`, `/panel`, `/ownerhelp`, `/ban`, `/unban`, `/addlimit`, `/userinfo`, `/free`, `/userlist`, `/broadcast`, `/setadmingroup`, `/setadmingroup_private`, `/accept`, `/deletevideo`, `/deleteprivatevideo`, `/deletephoto`, `/deleteprivatephoto`, `/removethumb`.

## Existing callback identifiers observed
- Explicit equality callbacks: `view_profile`, `channel_not_configured`, `gender_male`, `gender_female`, `noop`.
- Pattern callbacks: `rate_<video_id>_like`, `rate_<video_id>_dislike`.
- Additional dynamic handlers include channel-join refresh, album/media processing, text input, and owner workflows; preserve their predicates and data formats.

## Invariants — do not change in UI-only work
1. Command names, handler predicates, and callback_data values.
2. Owner authorization checks and user ban restrictions.
3. MongoDB database, collection names, document keys, and update semantics.
4. Referral attribution and pending-action flow.
5. Video/photo delivery, album handling, ratings, and counters.
6. Webhook route `/webhook`, health endpoint behavior, Render port, and startup sequence.
7. Existing environment variable compatibility (`OWNER_IDS` and legacy `OWNER_ID`).

## First UI-only change
The `send_welcome` message copy and presentation were refreshed for clearer hierarchy and a more polished brand voice. The function signature, dynamic total-video lookup, HTML parse mode, keyboard builder, callback identifiers, and database behavior remain unchanged. The reply-keyboard button labels were deliberately not renamed because they may be consumed by text handlers.

## Verification status
- Repository source and key UI handlers inspected before editing.
- GitHub Actions run [`38056033779`](https://github.com/helloeveryone100200-cell/blue-bot/actions/runs/38056033779) passed on the dashboard-inclusive revision: full-file `python -m py_compile bot.py`, eight static regression tests, and `node --check admin/app.js`.
- Static regression tests parse the source without importing `bot.py`, avoiding Telegram/MongoDB initialization and secrets, and verify the dashboard remains a non-connected prototype.
- Telegram integration/runtime tests: pending; no bot token or live test environment used.
- Render deployment/health verification: pending.
- Added a static dashboard prototype under `admin/` with responsive Premium Dark styling and clearly labelled illustrative data. It does not expose a dashboard route, call live APIs, or read production state.
- Dashboard authentication, server-side owner authorization, read-only API integration, and Render routing remain future work.
- This branch is a proposal; `main` has not been changed by this branch operation.

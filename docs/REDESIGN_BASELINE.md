# Blue Bot Redesign — Baseline & Behavior Audit

## Scope
- Repository: `helloeveryone100200-cell/blue-bot`
- Baseline branch: `main`
- Implementation branch: `redesign/premium-dark-safe-ui`
- Design direction: Premium Dark (Deep Navy + Indigo)
- First change scope: Telegram welcome-message presentation only.

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
- GitHub Actions run [`38055860013`](https://github.com/helloeveryone100200-cell/blue-bot/actions/runs/38055860013) passed: full-file `python -m py_compile bot.py` and five static regression tests.
- Static regression tests parse the source without importing `bot.py`, avoiding Telegram/MongoDB initialization and secrets.
- Telegram integration/runtime tests: pending; no bot token or live test environment used.
- Render deployment/health verification: pending.
- Dashboard frontend work is the next isolated phase; no dashboard route or API is exposed by this baseline change.
- This branch is a proposal; `main` has not been changed by this branch operation.

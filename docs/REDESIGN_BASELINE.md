# Blue Bot Redesign — Baseline & Behavior Audit

## Scope
- Repository: `helloeveryone100200-cell/blue-bot`
- Baseline branch: `main`
- Implementation branch: `redesign/premium-dark-safe-ui`
- Design direction: Premium Dark (Deep Navy + Indigo)
- Admin surface: Telegram Mini App only; no standalone browser dashboard login.

## Baseline architecture
- Main application: `bot.py`
- Telegram framework: `pyTelegramBotAPI` / `telebot`
- Database: MongoDB, database `BlueBotDB`, collections `users`, `videos`, `settings`
- HTTP server and Telegram webhook are implemented in `bot.py`
- Render start command in `render.yaml`: `python3 bot.py`

## Existing behavior that must remain unchanged
1. Command names, handler predicates, and callback_data values.
2. Owner authorization checks and user ban restrictions.
3. MongoDB database, collection names, document keys, and update semantics.
4. Referral attribution and pending-action flow.
5. Video/photo delivery, album handling, ratings, and counters.
6. Webhook route `/webhook`, health endpoint behavior, Render port, and startup sequence.
7. Existing environment variable compatibility (`OWNER_IDS` and legacy `OWNER_ID`).

## Mini App implementation
- `/admin/` serves the static Telegram Mini App shell and assets.
- Dashboard API access is POST-only at `/admin/api/overview`.
- The server validates Telegram Web App `initData` using `BOT_TOKEN`, rejects malformed/duplicate fields and stale/future auth dates, and authorizes only IDs in `OWNER_IDS` (with legacy `OWNER_ID` fallback).
- The API returns aggregate overview counts only; no user records, media identifiers, or write operations are exposed.
- The browser shell does not render the dashboard outside Telegram. Static assets are necessarily hosted over HTTPS so Telegram can load the Mini App.
- Telegram menu-button configuration sets the default Commands button and assigns the Web App menu button only to configured owner IDs.
- User Management, Media Library, and Bot Settings shortcuts are explicitly placeholders; they are not represented as implemented features.

## Metrics definition
- Users: count of documents in `users`.
- Videos: documents whose existing IDs match `vN` or `zN` (public and private video records).
- Photos: documents with `type: "photo_only"` (public and private standalone photo records).
- Media: videos plus photos. This avoids classifying private photo IDs (`zpN`) as videos.

## Verification status
- GitHub Actions run `38058507498` passed on commit `e10611dc7311ff9011dfd7469603ae87e3c08d4a` before the follow-up metric correction.
- Follow-up metric correction requires a new CI run before being considered validated.
- Telegram owner/non-owner live integration and Render deployment health have not been verified.
- This is a proposal branch; `main` has not been changed by this work.

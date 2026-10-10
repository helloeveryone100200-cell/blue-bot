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
- The `/start` welcome keyboard adds a direct **Admin Panel** Web App button only for owner IDs, so owners can launch the Mini App without changing ordinary users' keyboard.
- Mini App URLs are HTTPS-only; configured `/admin` URLs are normalized and fallback base URLs ending in `/webhook` are normalized to the service root.
- User Management, Media Library, and Bot Settings shortcuts are explicitly placeholders; they are not represented as implemented features.

## Metrics definition
- Users: count of documents in `users`.
- Videos: documents whose existing IDs match `vN` or `zN` (public and private video records).
- Photos: documents with `type: "photo_only"` (public and private standalone photo records).
- Media: videos plus photos. This avoids classifying private photo IDs (`zpN`) as videos.

## Verification status
- Latest automated checks are tracked in [GitHub Actions](https://github.com/helloeveryone100200-cell/blue-bot/actions); the current PR head is `b3a1fdb8a9a9cbb81fba8cc8d4978a9cc06c1a45`. The documentation-only commit is awaiting its CI run.
- Prior run `38059778006` passed on commit `bb0c39198a3a34b7f978e492c4db7a8cdbbc1c2e`, including Python compilation, regression tests, and JavaScript syntax validation.
- The regression suite includes initData authentication, aggregate API behavior, database-failure handling, body-size limits, owner-only launch UI, and runtime HTTPS URL resolution tests.
- Render service `blue-bot` currently tracks `main`; the PR branch is intentionally not deployed to production.
- Telegram owner/non-owner live integration, production MongoDB correctness, and deployment health for this PR branch have not been verified.
- PR #2 remains open and Draft; `main` has not been changed by this work.

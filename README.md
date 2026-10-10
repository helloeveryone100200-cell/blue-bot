# Blue Bot

A Telegram bot with a Telegram-only owner Mini App, video database, referral system, and owner control panel.

## Features

- Video database built from a Telegram admin group
- Album (media group) and single video support
- User limit system with referral tracking (+5 limit per referral)
- Customer support system (/contact_to_owner)
- Owner control panel (/panel, /free, /broadcast)
- Telegram Mini App with owner-only aggregate dashboard, paginated read-only user directory, and media inventory (no browser password dashboard)
- Anti-spam animation before video delivery
- HTTP keep-alive server for UptimeRobot on port 8080

## Setup on Render

1. Create a new **Web Service** on [render.com](https://render.com)
2. Connect your GitHub repo: `https://github.com/helloeveryone100200-cell/blue-bot`
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `python bot.py`
5. Add these **Environment Variables**:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | Your Telegram bot token from @BotFather |
| `MONGO_URI` | Your MongoDB Atlas connection string |
| `OWNER_IDS` | Comma-separated Telegram user IDs allowed to access owner controls and the Mini App (for example, `1827336632`) |
| `ADMIN_GROUP_ID` | Your admin group ID (e.g. `-1001234567890`) |
| `BOT_USERNAME` | Your bot's username without @ (e.g. `MyBlueBot`) |
| `PORT` | `8080` |
| `ADMIN_WEBAPP_URL` | Optional HTTPS Mini App URL; defaults to `https://<your-render-service>/admin/` when `RENDER_EXTERNAL_URL` is available. |



The owner Mini App opens from the Telegram menu button and, for owner accounts, an **Admin Panel** button in the `/start` welcome message. Regular users do not receive that Web App button. The Mini App validates Telegram Web App `initData` server-side against `BOT_TOKEN` and `OWNER_IDS`. It provides aggregate overview metrics, a paginated searchable read-only user directory, and a searchable/paginated media inventory with public/private visibility and metadata only. User records and media cannot be changed from the Mini App, and Telegram file IDs are never sent to the browser. Opening `/admin/` in an ordinary browser does not grant access to either API. No `ADMIN_DASHBOARD_PASSWORD` or `ADMIN_SESSION_SECRET` is required.

## Push to GitHub (secure method)

> **Security notice:** Never paste GitHub tokens in chat or public places.
> Always use them as environment variables or Git credential helpers.

```bash
# From the telegram-bot/ folder
git init
git remote add origin https://github.com/helloeveryone100200-cell/blue-bot.git
git add .
git commit -m "Initial commit: Blue Bot"
# Use your NEW token (revoke the old one first at github.com/settings/tokens)
git push https://<YOUR_NEW_TOKEN>@github.com/helloeveryone100200-cell/blue-bot.git main
```

## MongoDB Atlas

Database name: `BlueBotDB`  
Collections: `users`, `videos`, `settings`

The bot auto-initialises the `video_counter` settings document on first run.

## Commands

| Command | Who | Description |
|---------|-----|-------------|
| `/start` | Users | Welcome message + referral handling |
| `/contact_to_owner` | Users | Start a support message to owner |
| `/panel` | Owner only | Bot statistics |
| `/free {id} on\|off` | Owner only | Toggle unlimited views for a user |
| `/broadcast {id}` | Owner only | Reply to a specific user |

## UptimeRobot

Add a monitor pointing to your Render service URL (e.g. `https://blue-bot.onrender.com`).  
The bot responds with HTTP 200 on any GET request to keep the service alive.

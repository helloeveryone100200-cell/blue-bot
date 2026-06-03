# Blue Bot

A Telegram bot with video database, referral system, and owner control panel.

## Features

- Video database built from a Telegram admin group
- Album (media group) and single video support
- User limit system with referral tracking (+5 limit per referral)
- Customer support system (/contact_to_owner)
- Owner control panel (/panel, /free, /broadcast)
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
| `OWNER_ID` | `1827336632` |
| `ADMIN_GROUP_ID` | Your admin group ID (e.g. `-1001234567890`) |
| `BOT_USERNAME` | Your bot's username without @ (e.g. `MyBlueBot`) |
| `PORT` | `8080` |

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

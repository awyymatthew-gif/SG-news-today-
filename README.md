# 🇸🇬 SG Ground Sense News Bot

A Telegram bot that aggregates and ranks the top Singapore news and ground-sense posts, delivered 3× daily.

## Sources

- Reddit: r/singapore, r/SingaporeRaw, r/askSingapore
- HardwareZone EDMW
- Telegram channels: @cnalatest, @todayonlinesg, @straitstimes, @Govsg

## Schedule (Singapore Time)

| Time | Digest |
|---|---|
| 8:00 AM SGT | Morning briefing |
| 12:00 PM SGT | Midday update |
| 9:00 PM SGT | Evening wrap-up |

On-demand: send `/digest` to the bot anytime.

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message and schedule |
| `/digest` | Generate and send the latest digest now |
| `/help` | Show available commands |
| `/users` | (Admin only) Show registered user count and list |

## Deployment on Render

### Environment Variables

Set these in the Render dashboard for each service:

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID (default delivery target) |
| `ADMIN_CHAT_ID` | Chat ID that can use `/users` command |

### Services

- **Background Worker** (`listener.py`) — runs 24/7, handles `/digest` on-demand commands
- **Cron Job × 3** (`bot.py`) — runs at 00:00, 04:00, 13:00 UTC (8 AM, 12 PM, 9 PM SGT)

### Render Plan

The **Starter plan ($7/month)** is sufficient for the background worker.  
Cron jobs are billed at **$0.00016/minute** (Starter instance) — 3 daily runs of ~2 min each ≈ **$0.03/month**.

Total estimated cost: **~$7.10/month** for up to any number of Telegram users.

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export TELEGRAM_BOT_TOKEN="your_token_here"
export TELEGRAM_CHAT_ID="your_chat_id"

# Run a digest manually
python bot.py

# Start the listener
python listener.py
```

## File Structure

```
sg_news_bot/
├── bot.py          # Main digest runner
├── listener.py     # Telegram polling listener (24/7)
├── sources.py      # Fetches from Reddit, HWZ, Telegram channels
├── scorer.py       # Scores and ranks posts
├── digest.py       # Formats the digest message
├── config.py       # Configuration and environment variables
├── render.yaml     # Render deployment config
├── requirements.txt
└── README.md
```

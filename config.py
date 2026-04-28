"""
Configuration for Singapore Ground Sense News Bot.
Credentials are loaded from environment variables.
"""
import os

# Telegram Bot Token - set via environment variable TELEGRAM_BOT_TOKEN
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# Target Telegram chat ID
TELEGRAM_CHAT_ID = int(os.environ.get("TELEGRAM_CHAT_ID", "472397582"))

# Reddit API credentials - set via environment variables
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.environ.get("REDDIT_USER_AGENT", "SGNewsBot/1.0")

# Reddit subreddits to monitor
REDDIT_SUBREDDITS = ["singapore", "SingaporeRaw", "askSingapore"]

# HardwareZone EDMW RSS / scrape URL
HWZ_EDMW_URL = "https://forums.hardwarezone.com.sg/forums/eat-drink-man-woman.16/"

# Telegram channels to monitor (public)
TELEGRAM_CHANNELS = [
    "@cnalatest",
    "@todayonlinesg",
    "@mothershipsg",
    "@TheStraitsTimes",
    "@Govsg",
]

# Number of top posts to include in digest
TOP_N = 15

# Scoring weights
SCORE_WEIGHTS = {
    "upvotes": 1.0,
    "comments": 2.0,
    "recency_hours": -3.0,  # strong penalty per hour old — fresh news wins
}

# Hours lookback for posts
# Each digest covers the window since the previous digest:
# Morning (8AM): last 11h  |  Midday (12PM): last 4h  |  Evening (9PM): last 9h
# Use 6h as a balanced default — keeps content fresh and same-day
LOOKBACK_HOURS = 6

# Log file paths
BOT_LOG = "/home/ubuntu/sg_news_bot/bot.log"
LISTENER_LOG = "/home/ubuntu/sg_news_bot/listener.log"

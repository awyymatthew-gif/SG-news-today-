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
    "@mothership_sg",
    "@straitstimes",
    "@Govsg",
]

# Number of top posts to include in digest
TOP_N = 15

# Scoring weights
SCORE_WEIGHTS = {
    "upvotes": 1.0,
    "comments": 2.0,
    "recency_hours": -0.5,  # penalty per hour old
}

# Hours lookback for posts
LOOKBACK_HOURS = 12

# Log file paths
BOT_LOG = "/home/ubuntu/sg_news_bot/bot.log"
LISTENER_LOG = "/home/ubuntu/sg_news_bot/listener.log"

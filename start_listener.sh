#!/bin/bash
# Start the SG Ground Sense Bot listener
cd /home/ubuntu/sg_news_bot
source /home/ubuntu/.env 2>/dev/null || true
source /home/ubuntu/.user_env 2>/dev/null || true

# Load bot-specific env if exists
if [ -f /home/ubuntu/sg_news_bot/.env ]; then
    source /home/ubuntu/sg_news_bot/.env
fi

exec python3 /home/ubuntu/sg_news_bot/listener.py

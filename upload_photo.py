"""Upload profile photo to Telegram bot."""
import requests

TOKEN = "8700784836:AAGB2d0rxUijlCMS5j2uKOTlbA9WVpAmFi8"
BASE = f"https://api.telegram.org/bot{TOKEN}"

with open("/home/ubuntu/sg_news_bot/bot_profile_small.png", "rb") as f:
    resp = requests.post(
        f"{BASE}/setMyPhoto",
        files={"photo": ("bot_profile_small.png", f, "image/png")},
        timeout=60,
    )
    result = resp.json()
    print(f"setMyPhoto: {'OK' if result.get('ok') else 'FAIL'} — {result}")

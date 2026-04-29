import requests
import os

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8700784836:AAGB2d0rxUijlCMS5j2uKOTlbA9WVpAmFi8")
CHAT_ID = 472397582

msg = (
    "SG Ground Sense News Bot is now deployed on Render and running 24/7.\n\n"
    "You will receive automatic digests at:\n"
    "  8:00 AM SGT - Morning briefing\n"
    "  12:00 PM SGT - Midday update\n"
    "  9:00 PM SGT - Evening wrap-up\n\n"
    "Send /digest anytime for an on-demand update."
)

r = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/sendMessage",
    json={"chat_id": CHAT_ID, "text": msg}
)
print("Sent" if r.json().get("ok") else f"Failed: {r.text}")

"""Set up Telegram bot profile: name, description, about, commands, and photo."""
import requests
import os

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8700784836:AAGB2d0rxUijlCMS5j2uKOTlbA9WVpAmFi8")
BASE = f"https://api.telegram.org/bot{TOKEN}"


def api(method, **kwargs):
    resp = requests.post(f"{BASE}/{method}", json=kwargs, timeout=15)
    result = resp.json()
    print(f"{method}: {'OK' if result.get('ok') else 'FAIL'} — {result}")
    return result


# 1. Set display name
api("setMyName", name="SG Ground Sense News Bot")

# 2. Set description (shown on bot's profile page / start screen)
api("setMyDescription", description=(
    "🇸🇬 Your daily Singapore ground-sense digest.\n\n"
    "Aggregates top posts from:\n"
    "• Reddit SG (r/singapore, r/SingaporeRaw, r/askSingapore)\n"
    "• HardwareZone EDMW\n"
    "• Telegram: CNA, Today Online, Straits Times, GovSG\n\n"
    "Scored, ranked, and delivered 3× daily.\n"
    "Scheduled: 8 AM, 12 PM, 9 PM SGT\n"
    "On-demand: /digest"
))

# 3. Set short description (shown in search results)
api("setMyShortDescription", short_description=(
    "🇸🇬 Daily SG news digest from Reddit, HWZ EDMW & Telegram channels. /digest for on-demand updates."
))

# 4. Set bot commands
api("setMyCommands", commands=[
    {"command": "digest", "description": "Generate and send the latest Singapore news digest"},
    {"command": "help", "description": "Show available commands and schedule"},
    {"command": "start", "description": "Start the bot and see what it does"},
])

print("\nBot profile setup complete.")

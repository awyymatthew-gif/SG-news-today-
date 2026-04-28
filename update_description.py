"""Update Telegram bot description to include scheduled digest times in SGT."""
import requests

TOKEN = "8700784836:AAGB2d0rxUijlCMS5j2uKOTlbA9WVpAmFi8"
BASE = f"https://api.telegram.org/bot{TOKEN}"


def api(method, **kwargs):
    resp = requests.post(f"{BASE}/{method}", json=kwargs, timeout=15)
    result = resp.json()
    print(f"{method}: {'OK' if result.get('ok') else 'FAIL'} — {result}")
    return result


# Full description (shown on bot profile page / when user taps the bot name)
api("setMyDescription", description=(
    "🇸🇬 Your daily Singapore ground-sense digest.\n\n"
    "Aggregates and ranks the top posts from:\n"
    "• Reddit: r/singapore, r/SingaporeRaw, r/askSingapore\n"
    "• HardwareZone EDMW\n"
    "• Telegram: CNA, Today Online, Straits Times, GovSG\n\n"
    "🕗 Auto-digest schedule (Singapore Time):\n"
    "   • 8:00 AM SGT — Morning briefing\n"
    "   • 12:00 PM SGT — Midday update\n"
    "   • 9:00 PM SGT — Evening wrap-up\n\n"
    "📲 On-demand: Send /digest anytime for the latest digest."
))

# Short description (shown in search results and chat list previews)
api("setMyShortDescription", short_description=(
    "🇸🇬 SG news digest auto-sent at 8AM, 12PM & 9PM SGT. "
    "Sources: Reddit SG, HWZ EDMW, CNA, ST & more. "
    "Send /digest anytime."
))

print("\nBot description updated.")

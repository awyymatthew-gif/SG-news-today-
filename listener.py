"""
Singapore Ground Sense News Bot - Telegram Command Listener
Listens for /digest, /start, /help, /users commands via Telegram bot polling.
Tracks all users who interact with the bot in users.json.
"""
import logging
import sys
import time
import subprocess
import os
import json
import requests
from datetime import datetime, timezone
from config import TELEGRAM_BOT_TOKEN, LISTENER_LOG

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LISTENER_LOG),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("listener")

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
OFFSET_FILE = os.path.join(BOT_DIR, ".listener_offset")
USERS_FILE = os.path.join(BOT_DIR, "users.json")

# Admin chat ID — only this user can see /users stats
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "472397582"))


# ── User tracking ────────────────────────────────────────────────────────────

def load_users():
    """Load the users registry from disk."""
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(users):
    """Persist the users registry to disk."""
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save users: {e}")


def record_user(message):
    """Record or update a user entry from a Telegram message object."""
    from_data = message.get("from", {})
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    if not chat_id:
        return

    users = load_users()
    now = datetime.now(timezone.utc).isoformat()

    if chat_id not in users:
        users[chat_id] = {
            "chat_id": chat_id,
            "username": from_data.get("username", ""),
            "first_name": from_data.get("first_name", ""),
            "last_name": from_data.get("last_name", ""),
            "first_seen": now,
            "last_seen": now,
            "message_count": 1,
        }
        logger.info(f"New user registered: {from_data.get('username', chat_id)}")
    else:
        users[chat_id]["last_seen"] = now
        users[chat_id]["message_count"] = users[chat_id].get("message_count", 0) + 1
        # Update name fields in case they changed
        users[chat_id]["username"] = from_data.get("username", users[chat_id].get("username", ""))
        users[chat_id]["first_name"] = from_data.get("first_name", users[chat_id].get("first_name", ""))

    save_users(users)
    return users


# ── Offset management ─────────────────────────────────────────────────────────

def load_offset():
    try:
        with open(OFFSET_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def save_offset(offset):
    try:
        with open(OFFSET_FILE, "w") as f:
            f.write(str(offset))
    except Exception as e:
        logger.error(f"Failed to save offset: {e}")


# ── Telegram API helpers ──────────────────────────────────────────────────────

def get_updates(offset=0, timeout=30):
    """Long-poll Telegram for new updates."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set.")
        return []

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {
        "offset": offset,
        "timeout": timeout,
        "allowed_updates": ["message"],
    }
    try:
        resp = requests.get(url, params=params, timeout=timeout + 10)
        data = resp.json()
        if data.get("ok"):
            return data.get("result", [])
        else:
            logger.error(f"getUpdates error: {data}")
            return []
    except requests.exceptions.Timeout:
        return []
    except Exception as e:
        logger.error(f"Error getting updates: {e}")
        return []


def send_reply(chat_id, text, parse_mode=None):
    """Send a reply to a specific chat."""
    if not TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        requests.post(url, json=payload, timeout=15)
    except Exception as e:
        logger.error(f"Error sending reply: {e}")


# ── Digest trigger ────────────────────────────────────────────────────────────

def trigger_digest():
    """Run bot.py as a subprocess to generate and send digest."""
    logger.info("Triggering digest run...")
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(BOT_DIR, "bot.py")],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=BOT_DIR,
        )
        if result.returncode == 0:
            logger.info("Digest triggered successfully.")
        else:
            logger.error(f"Digest run failed: {result.stderr}")
    except subprocess.TimeoutExpired:
        logger.error("Digest run timed out.")
    except Exception as e:
        logger.error(f"Error triggering digest: {e}")


# ── User stats command ────────────────────────────────────────────────────────

def handle_users_command(chat_id):
    """Send user stats to admin only."""
    if int(chat_id) != ADMIN_CHAT_ID:
        send_reply(chat_id, "⛔ This command is only available to the bot admin.")
        return

    users = load_users()
    count = len(users)
    if count == 0:
        send_reply(chat_id, "📊 No users tracked yet.")
        return

    lines = [f"📊 *Bot Users — {count} total*\n"]
    for uid, u in sorted(users.items(), key=lambda x: x[1].get("first_seen", ""), reverse=True):
        name = u.get("username") or u.get("first_name") or uid
        first = u.get("first_seen", "")[:10]
        last = u.get("last_seen", "")[:10]
        msgs = u.get("message_count", 0)
        lines.append(f"• @{name} — joined {first}, last active {last}, {msgs} msgs")

    send_reply(chat_id, "\n".join(lines), parse_mode="Markdown")


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_listener():
    logger.info("=" * 50)
    logger.info("SG Ground Sense Bot Listener starting...")
    logger.info("=" * 50)

    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set. Listener cannot start.")
        logger.info("Set TELEGRAM_BOT_TOKEN environment variable and restart.")
        while True:
            time.sleep(60)
            if os.environ.get("TELEGRAM_BOT_TOKEN"):
                logger.info("Token detected, restarting listener...")
                break

    offset = load_offset()
    logger.info(f"Starting from offset {offset}")

    consecutive_errors = 0
    while True:
        try:
            updates = get_updates(offset=offset, timeout=30)
            consecutive_errors = 0

            for update in updates:
                update_id = update.get("update_id", 0)
                offset = update_id + 1
                save_offset(offset)

                message = update.get("message", {})
                if not message:
                    continue

                text = message.get("text", "").strip()
                chat_id = message.get("chat", {}).get("id")
                username = message.get("from", {}).get("username", "unknown")

                # Track every user who sends any message
                record_user(message)

                logger.info(f"Received message from {username} (chat {chat_id}): {text}")

                cmd = text.lower().split("@")[0]  # strip @botname suffix

                if cmd == "/digest":
                    logger.info(f"Digest command received from {username}")
                    send_reply(chat_id, "⏳ Generating digest, please wait...")
                    trigger_digest()

                elif cmd in ["/start", "/help"]:
                    send_reply(
                        chat_id,
                        "🇸🇬 *SG Ground Sense Bot*\n\n"
                        "I send you the top Singapore news and ground-sense posts daily.\n\n"
                        "*Auto-digest schedule (SGT):*\n"
                        "🕗 8:00 AM — Morning briefing\n"
                        "🕛 12:00 PM — Midday update\n"
                        "🕘 9:00 PM — Evening wrap-up\n\n"
                        "*Commands:*\n"
                        "/digest — Get the latest digest now\n"
                        "/help — Show this message",
                        parse_mode="Markdown",
                    )

                elif cmd == "/users":
                    handle_users_command(chat_id)

        except KeyboardInterrupt:
            logger.info("Listener stopped by user.")
            break
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Listener error (#{consecutive_errors}): {e}")
            sleep_time = min(60, 5 * consecutive_errors)
            logger.info(f"Retrying in {sleep_time}s...")
            time.sleep(sleep_time)


if __name__ == "__main__":
    run_listener()

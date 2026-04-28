"""
SG News Bot - Telegram Command Listener
Listens for /digest, /start, /help, /users, /stats commands via long-polling.
Runs 24/7 on Render as a Background Worker.
"""
import logging
import sys
import time
import os
import json
import requests
from datetime import datetime, timezone
from config import TELEGRAM_BOT_TOKEN, LISTENER_LOG

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),  # Render captures stdout
    ],
)
logger = logging.getLogger("listener")

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
OFFSET_FILE = os.path.join(BOT_DIR, ".listener_offset")
USERS_FILE = os.path.join(BOT_DIR, "users.json")

ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "472397582"))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"


# ── User tracking ─────────────────────────────────────────────────────────────

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(users):
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save users: {e}")


def record_user(message):
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
        logger.info(f"New user: {from_data.get('username', chat_id)}")
    else:
        users[chat_id]["last_seen"] = now
        users[chat_id]["message_count"] = users[chat_id].get("message_count", 0) + 1
        users[chat_id]["username"] = from_data.get("username", users[chat_id].get("username", ""))
        users[chat_id]["first_name"] = from_data.get("first_name", users[chat_id].get("first_name", ""))
    save_users(users)


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
    try:
        resp = requests.get(
            f"{BASE_URL}/getUpdates",
            params={"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
            timeout=timeout + 15,
        )
        data = resp.json()
        if data.get("ok"):
            return data.get("result", [])
        logger.error(f"getUpdates error: {data}")
        return []
    except requests.exceptions.Timeout:
        return []
    except Exception as e:
        logger.error(f"getUpdates exception: {e}")
        return []


def send_message(chat_id, text, parse_mode=None):
    """Send a message to a specific chat."""
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        resp = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=15)
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"sendMessage error: {data}")
    except Exception as e:
        logger.error(f"sendMessage exception: {e}")


# ── Digest trigger ────────────────────────────────────────────────────────────

def trigger_digest(reply_chat_id):
    """Run the full digest pipeline and send result to reply_chat_id."""
    logger.info(f"Triggering digest for chat {reply_chat_id}...")
    try:
        # Import inline to avoid circular issues and pick up env at runtime
        from sources import fetch_all_sources
        from scorer import rank_posts
        from digest import format_digest, format_digest_plain

        all_posts = fetch_all_sources()
        if not all_posts:
            send_message(reply_chat_id, "⚠️ No posts could be fetched right now. Try again in a few minutes.")
            return

        ranked = rank_posts(all_posts)
        digest_text = format_digest(ranked)

        # Send — split if needed
        MAX = 4096
        if len(digest_text) <= MAX:
            chunks = [digest_text]
        else:
            chunks = []
            current = ""
            for line in digest_text.split("\n"):
                if len(current) + len(line) + 1 > MAX:
                    chunks.append(current)
                    current = line
                else:
                    current += "\n" + line if current else line
            if current:
                chunks.append(current)

        for chunk in chunks:
            resp = requests.post(
                f"{BASE_URL}/sendMessage",
                json={"chat_id": reply_chat_id, "text": chunk,
                      "parse_mode": "MarkdownV2", "disable_web_page_preview": True},
                timeout=30,
            )
            data = resp.json()
            if not data.get("ok"):
                # Fallback to plain text
                plain = format_digest_plain(ranked)
                send_message(reply_chat_id, plain[:MAX])
                break

        logger.info(f"Digest sent to chat {reply_chat_id}")
    except Exception as e:
        logger.error(f"Digest trigger failed: {e}")
        send_message(reply_chat_id, "⚠️ Digest generation failed. Please try again.")


# ── Admin commands ────────────────────────────────────────────────────────────

def handle_users_command(chat_id):
    if int(chat_id) != ADMIN_CHAT_ID:
        return  # Silent for non-admins
    users = load_users()
    count = len(users)
    if count == 0:
        send_message(chat_id, "📊 No users tracked yet.")
        return
    lines = [f"📊 *Bot Users — {count} total*\n"]
    for uid, u in sorted(users.items(), key=lambda x: x[1].get("first_seen", ""), reverse=True):
        name = u.get("username") or u.get("first_name") or uid
        first = u.get("first_seen", "")[:10]
        last = u.get("last_seen", "")[:10]
        msgs = u.get("message_count", 0)
        lines.append(f"• @{name} — joined {first}, last active {last}, {msgs} msgs")
    send_message(chat_id, "\n".join(lines), parse_mode="Markdown")


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_listener():
    logger.info("=" * 50)
    logger.info("SG News Bot Listener starting on Render...")
    logger.info(f"Token present: {bool(TOKEN)}")
    logger.info(f"Admin chat ID: {ADMIN_CHAT_ID}")
    logger.info("=" * 50)

    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set — listener cannot start.")
        # Keep process alive so Render doesn't restart-loop
        while True:
            time.sleep(60)

    offset = load_offset()
    logger.info(f"Starting from offset {offset}")

    consecutive_errors = 0
    while True:
        try:
            updates = get_updates(offset=offset, timeout=30)
            consecutive_errors = 0  # reset on success

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

                record_user(message)
                logger.info(f"Message from @{username} ({chat_id}): {text}")

                # Strip @botname suffix from commands
                cmd = text.lower().split("@")[0]

                if cmd in ["/digest"]:
                    send_message(chat_id, "⏳ Fetching latest SG news, please wait...")
                    trigger_digest(chat_id)

                elif cmd in ["/start", "/help"]:
                    send_message(
                        chat_id,
                        "🇸🇬 *SG News*\n"
                        "Top 15 Singapore stories, 3× a day.\n\n"
                        "🕗 8AM  •  🕛 12PM  •  🕘 9PM\n\n"
                        "Tap /digest to get the latest digest now.",
                        parse_mode="Markdown",
                    )

                elif cmd in ["/stats", "/users"]:
                    handle_users_command(chat_id)

        except KeyboardInterrupt:
            logger.info("Listener stopped.")
            break
        except Exception as e:
            consecutive_errors += 1
            wait = min(60, 5 * consecutive_errors)
            logger.error(f"Listener error #{consecutive_errors}: {e} — retrying in {wait}s")
            time.sleep(wait)


if __name__ == "__main__":
    run_listener()

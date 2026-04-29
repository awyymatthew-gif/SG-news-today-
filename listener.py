"""
SG News Bot - Telegram Command Listener
Listens for /digest, /start, /help, /users, /stats commands via long-polling.
Runs 24/7 on Render as a Background Worker.
Uses SQLite (db.py) on Render's persistent disk — offset and users survive restarts.
"""
import logging
import sys
import time
import os
import requests
from config import TELEGRAM_BOT_TOKEN
import db

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),  # Render captures stdout
    ],
)
logger = logging.getLogger("listener")

ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "472397582"))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"


# ── Telegram API helpers ──────────────────────────────────────────────────────

def get_updates(offset=0, timeout=30):
    """Long-poll Telegram for new updates."""
    try:
        resp = requests.get(
            f"{BASE_URL}/getUpdates",
            params={"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
            timeout=timeout + 10,
        )
        data = resp.json()
        if data.get("ok"):
            return data.get("result", [])
        else:
            logger.error(f"getUpdates error: {data}")
            return []
    except Exception as e:
        logger.error(f"getUpdates exception: {e}")
        return []


def send_message(chat_id, text, parse_mode=None):
    """Send a Telegram message, splitting if over 4096 chars."""
    chunks = [text[i:i+4096] for i in range(0, len(text), 4096)]
    for chunk in chunks:
        payload = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
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
    try:
        from sources import fetch_all_sources
        from scorer import rank_posts
        from digest import format_digest, format_digest_plain
        from config import TELEGRAM_CHAT_ID

        db.init_db()

        all_posts = fetch_all_sources()
        if not all_posts:
            send_message(reply_chat_id, "⚠️ Could not fetch any posts right now. Try again in a minute.")
            return

        # Filter already-sent posts
        fresh = [p for p in all_posts if not db.is_already_sent(p)]
        if not fresh:
            send_message(reply_chat_id, "📭 No new stories since the last digest.")
            return

        ranked = rank_posts(fresh)
        digest_text = format_digest(ranked)

        # Send to the requesting chat
        chunks = [digest_text[i:i+4096] for i in range(0, len(digest_text), 4096)]
        for chunk in chunks:
            payload = {
                "chat_id": reply_chat_id,
                "text": chunk,
                "parse_mode": "MarkdownV2",
                "disable_web_page_preview": True,
            }
            try:
                resp = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=30)
                data = resp.json()
                if not data.get("ok"):
                    logger.error(f"Digest send error: {data}")
                    # Fallback to plain text
                    plain = format_digest_plain(ranked)
                    plain_chunks = [plain[i:i+4096] for i in range(0, len(plain), 4096)]
                    for pc in plain_chunks:
                        requests.post(f"{BASE_URL}/sendMessage", json={
                            "chat_id": reply_chat_id,
                            "text": pc,
                            "disable_web_page_preview": True,
                        }, timeout=30)
                    break
            except Exception as e:
                logger.error(f"Digest send exception: {e}")

        db.mark_sent(ranked)
        db.prune_sent_posts(keep_days=3)
        logger.info(f"On-demand digest sent to {reply_chat_id}")

    except Exception as e:
        logger.error(f"trigger_digest error: {e}")
        send_message(reply_chat_id, f"❌ Error generating digest: {e}")


# ── /users command ────────────────────────────────────────────────────────────

def handle_users_command(chat_id):
    if int(chat_id) != ADMIN_CHAT_ID:
        return  # Silent for non-admins
    users = db.get_all_users()
    count = len(users)
    if count == 0:
        send_message(chat_id, "📊 No users tracked yet.")
        return
    lines = [f"📊 *Bot Users — {count} total*\n"]
    for u in sorted(users, key=lambda x: x.get("first_seen", ""), reverse=True):
        name = u.get("username") or u.get("first_name") or u.get("chat_id")
        first = (u.get("first_seen") or "")[:10]
        last  = (u.get("last_seen") or "")[:10]
        msgs  = u.get("message_count", 0)
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
        while True:
            time.sleep(60)

    # Initialise SQLite DB
    db.init_db()

    # Load offset from DB (survives restarts)
    offset = int(db.get_state("telegram_offset", 0))
    logger.info(f"Starting from offset {offset}")

    consecutive_errors = 0

    while True:
        try:
            updates = get_updates(offset=offset, timeout=30)
            consecutive_errors = 0  # reset on success

            for update in updates:
                update_id = update.get("update_id", 0)
                offset = update_id + 1
                db.set_state("telegram_offset", offset)  # persist immediately

                message = update.get("message", {})
                if not message:
                    continue

                text    = message.get("text", "").strip()
                chat_id = message.get("chat", {}).get("id")
                username = message.get("from", {}).get("username", "unknown")

                db.upsert_user(message)
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

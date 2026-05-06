"""
SG News Bot - Telegram Command Listener + Built-in Scheduler
Listens for /digest, /start, /help, /users, /stats commands via long-polling.
Also runs the 3 daily digests internally (7:30AM, 12PM, 9PM SGT) using a
background thread — no separate Render cron jobs needed.

Runs 24/7 on Render as a Background Worker.
Uses SQLite (db.py) on Render's persistent disk — offset and users survive restarts.
"""
import logging
import sys
import time
import os
import re
import threading
import requests
import schedule
import pytz
import datetime

from config import TELEGRAM_BOT_TOKEN
import db
from sources import fetch_all_sources
from scorer import rank_posts
from digest import format_digest_chunks

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
CHAT_ID       = int(os.environ.get("TELEGRAM_CHAT_ID", "472397582"))
TOKEN         = os.environ.get("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
BASE_URL      = f"https://api.telegram.org/bot{TOKEN}"
SGT           = pytz.timezone("Asia/Singapore")

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


def send_digest_chunks(chat_id, chunks):
    """Send pre-formatted MarkdownV2 digest chunks to a chat, with plain-text fallback."""
    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=30)
            data = resp.json()
            if not data.get("ok"):
                logger.error(f"Digest send error: {data}")
                # Fallback: strip MarkdownV2 escapes and send as plain text
                plain = re.sub(r'\\([_*\[\]()~`>#+=|{}.!\-])', r'\1', chunk)
                requests.post(f"{BASE_URL}/sendMessage", json={
                    "chat_id": chat_id,
                    "text": plain,
                    "disable_web_page_preview": True,
                }, timeout=30)
        except Exception as e:
            logger.error(f"Digest send exception: {e}")


# ── Core digest pipeline ──────────────────────────────────────────────────────
def run_digest_pipeline(target_chat_id=None):
    """
    Full digest pipeline: fetch -> deduplicate -> rank -> format -> send.
    target_chat_id: where to send the digest (defaults to CHAT_ID).
    """
    if target_chat_id is None:
        target_chat_id = CHAT_ID

    logger.info(f"=== Digest pipeline starting (target={target_chat_id}) ===")
    try:
        db.init_db()

        all_posts = fetch_all_sources()
        if not all_posts:
            logger.warning("No posts fetched from any source.")
            send_message(target_chat_id, "SG News: Could not fetch any posts right now.")
            return

        logger.info(f"Fetched {len(all_posts)} posts total")

        # Dedup: filter posts already sent in the last 8 hours
        fresh = [p for p in all_posts if not db.is_already_sent(p)]
        skipped = len(all_posts) - len(fresh)
        if skipped:
            logger.info(f"Filtered {skipped} already-sent posts -- {len(fresh)} fresh remain")

        # Fallback: if fewer than 5 fresh posts, ignore dedup entirely
        MIN_FRESH = 5
        if len(fresh) < MIN_FRESH:
            logger.warning(
                f"Only {len(fresh)} fresh posts after dedup (threshold={MIN_FRESH}). "
                f"Ignoring dedup -- using all {len(all_posts)} posts."
            )
            posts_to_rank = all_posts
        else:
            posts_to_rank = fresh

        ranked = rank_posts(posts_to_rank)
        logger.info(f"Ranked {len(ranked)} posts for digest")

        chunks = format_digest_chunks(ranked)
        logger.info(f"Digest split into {len(chunks)} message(s)")

        send_digest_chunks(target_chat_id, chunks)

        db.mark_sent(ranked)
        db.prune_sent_posts(keep_days=3)
        logger.info("=== Digest pipeline complete ===")

    except Exception as e:
        logger.error(f"Digest pipeline error: {e}", exc_info=True)
        try:
            send_message(target_chat_id, f"Digest error: {e}")
        except Exception:
            pass


# ── Scheduled digest jobs ─────────────────────────────────────────────────────
def scheduled_digest():
    """Called by the scheduler at 7:30AM, 12PM, and 9PM SGT."""
    now_sgt = datetime.datetime.now(SGT)
    logger.info(f"Scheduled digest triggered at {now_sgt.strftime('%H:%M SGT')}")
    run_digest_pipeline(CHAT_ID)


def _run_scheduler():
    """Background thread: runs the schedule loop forever."""
    logger.info("Scheduler thread running.")
    while True:
        schedule.run_pending()
        time.sleep(10)  # check every 10 seconds


def setup_schedule():
    """
    Register the 3 daily digest times.
    Render servers run in UTC, so we schedule at UTC equivalents of SGT times:
      7:30 AM SGT = 23:30 UTC (previous calendar day)
      12:00 PM SGT = 04:00 UTC
       9:00 PM SGT = 13:00 UTC
    """
    schedule.every().day.at("23:30").do(scheduled_digest)  # 7:30 AM SGT
    schedule.every().day.at("04:00").do(scheduled_digest)  # 12:00 PM SGT
    schedule.every().day.at("13:00").do(scheduled_digest)  # 9:00 PM SGT
    logger.info("Scheduled: 23:30 UTC (7:30AM SGT), 04:00 UTC (12PM SGT), 13:00 UTC (9PM SGT)")


# ── /digest command ───────────────────────────────────────────────────────────
def trigger_digest(reply_chat_id):
    """Handle /digest command -- run pipeline and send to requesting chat."""
    try:
        run_digest_pipeline(reply_chat_id)
    except Exception as e:
        logger.error(f"trigger_digest error: {e}")
        send_message(reply_chat_id, f"Error generating digest: {e}")


# ── /users command ────────────────────────────────────────────────────────────
def handle_users_command(chat_id):
    if int(chat_id) != ADMIN_CHAT_ID:
        return  # Silent for non-admins
    users = db.get_all_users()
    count = len(users)
    if count == 0:
        send_message(chat_id, "No users tracked yet.")
        return
    lines = [f"Bot Users -- {count} total\n"]
    for u in sorted(users, key=lambda x: x.get("first_seen", ""), reverse=True):
        name  = u.get("username") or u.get("first_name") or u.get("chat_id")
        first = (u.get("first_seen") or "")[:10]
        last  = (u.get("last_seen") or "")[:10]
        msgs  = u.get("message_count", 0)
        lines.append(f"- @{name} -- joined {first}, last active {last}, {msgs} msgs")
    send_message(chat_id, "\n".join(lines))


# ── Main loop ─────────────────────────────────────────────────────────────────
def run_listener():
    logger.info("=" * 50)
    logger.info("SG News Bot Listener + Scheduler starting on Render...")
    logger.info(f"Token present: {bool(TOKEN)}")
    logger.info(f"Chat ID: {CHAT_ID}")
    logger.info(f"Admin chat ID: {ADMIN_CHAT_ID}")
    logger.info("=" * 50)

    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set -- listener cannot start.")
        while True:
            time.sleep(60)

    # Initialise SQLite DB
    db.init_db()

    # Set up scheduled digests and start background scheduler thread
    setup_schedule()
    scheduler_thread = threading.Thread(target=_run_scheduler, daemon=True, name="scheduler")
    scheduler_thread.start()
    logger.info("Scheduler thread started -- digests will fire at 7:30AM, 12PM, 9PM SGT")

    # Load Telegram offset from DB (survives restarts)
    offset = int(db.get_state("telegram_offset", 0))
    logger.info(f"Starting Telegram polling from offset {offset}")

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

                text     = message.get("text", "").strip()
                chat_id  = message.get("chat", {}).get("id")
                username = message.get("from", {}).get("username", "unknown")

                db.upsert_user(message)
                logger.info(f"Message from @{username} ({chat_id}): {text}")

                # Strip @botname suffix from commands (e.g. /digest@Sgnewstodaybot)
                cmd = text.lower().split("@")[0]

                if cmd == "/digest":
                    send_message(chat_id, "Fetching latest SG news, please wait...")
                    trigger_digest(chat_id)

                elif cmd in ("/start", "/help"):
                    send_message(
                        chat_id,
                        "SG News\nTop 15 Singapore stories, 3x a day.\n\n"
                        "7:30AM  |  12PM  |  9PM\n\n"
                        "Tap /digest to get the latest digest now.",
                    )

                elif cmd in ("/stats", "/users"):
                    handle_users_command(chat_id)

        except KeyboardInterrupt:
            logger.info("Listener stopped.")
            break
        except Exception as e:
            consecutive_errors += 1
            wait = min(60, 5 * consecutive_errors)
            logger.error(f"Listener error #{consecutive_errors}: {e} -- retrying in {wait}s")
            time.sleep(wait)


if __name__ == "__main__":
    run_listener()

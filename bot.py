"""
Singapore Ground Sense News Bot - Main Digest Runner
Fetches from all sources, scores/ranks posts, generates and sends digest to Telegram.
Uses SQLite (db.py) on Render's persistent disk to prevent duplicate posts across runs.
"""
import logging
import sys
import os
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, BOT_LOG
from sources import fetch_all_sources
from scorer import rank_posts
from digest import format_digest, format_digest_chunks, format_digest_plain
import db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(BOT_LOG),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("bot")


def send_telegram_message(text, parse_mode="MarkdownV2"):
    """Send a message to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set. Cannot send message.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        data = resp.json()
        if data.get("ok"):
            logger.info(f"Message sent successfully to chat {TELEGRAM_CHAT_ID}")
            return True
        else:
            logger.error(f"Telegram API error: {data}")
            # Try plain text fallback
            if parse_mode != "HTML":
                logger.info("Retrying with plain text...")
                return send_telegram_message_plain(text)
            return False
    except Exception as e:
        logger.error(f"Error sending Telegram message: {e}")
        return False


def send_telegram_message_plain(text):
    """Send plain text message to Telegram (fallback)."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Strip markdown formatting for plain text
    plain = text.replace("\\.", ".").replace("\\-", "-").replace("\\_", "_")
    plain = plain.replace("\\!", "!").replace("\\(", "(").replace("\\)", ")")
    plain = plain.replace("\\[", "[").replace("\\]", "]").replace("\\>", ">")
    plain = plain.replace("\\#", "#").replace("\\+", "+").replace("\\=", "=")
    plain = plain.replace("\\|", "|").replace("\\{", "{").replace("\\}", "}")
    plain = plain.replace("\\~", "~").replace("\\`", "`").replace("\\*", "*")

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": plain,
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        data = resp.json()
        if data.get("ok"):
            logger.info("Plain text message sent successfully.")
            return True
        else:
            logger.error(f"Plain text send failed: {data}")
            return False
    except Exception as e:
        logger.error(f"Error sending plain text message: {e}")
        return False


def split_and_send(text, max_length=4096):
    """Split long messages and send in chunks."""
    if len(text) <= max_length:
        return send_telegram_message(text)

    parts = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_length:
            parts.append(current)
            current = line
        else:
            current += "\n" + line if current else line
    if current:
        parts.append(current)

    success = True
    for part in parts:
        if not send_telegram_message(part):
            success = False
    return success


def split_and_send_plain(text, max_length=4096):
    """Split and send plain text messages."""
    parts = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_length:
            parts.append(current)
            current = line
        else:
            current += "\n" + line if current else line
    if current:
        parts.append(current)

    for part in parts:
        send_telegram_message_plain(part)


def run_digest():
    """Main digest pipeline: fetch, score, rank, format, send."""
    logger.info("=" * 50)
    logger.info("Starting Singapore Ground Sense digest run")
    logger.info("=" * 50)

    # Initialise DB (creates tables if not present)
    db.init_db()

    # Step 1: Fetch from all sources
    logger.info("Step 1: Fetching from all sources...")
    all_posts = fetch_all_sources()

    if not all_posts:
        logger.warning("No posts fetched from any source.")
        msg = "⚠️ SG Ground Sense Bot: No posts could be fetched at this time."
        send_telegram_message_plain(msg)
        return

    logger.info(f"Total posts fetched: {len(all_posts)}")

    # Step 1b: Filter out posts already sent in a previous digest
    fresh_posts = [p for p in all_posts if not db.is_already_sent(p)]
    skipped = len(all_posts) - len(fresh_posts)
    if skipped:
        logger.info(f"Filtered {skipped} already-sent posts — {len(fresh_posts)} fresh posts remain")
    all_posts = fresh_posts

    if not all_posts:
        logger.warning("All fetched posts were already sent. Nothing new to digest.")
        send_telegram_message_plain("📭 No new stories since the last digest.")
        return

    # Step 2: Score and rank
    logger.info("Step 2: Scoring and ranking posts...")
    ranked = rank_posts(all_posts)
    logger.info(f"Top {len(ranked)} posts selected for digest")

    # Step 3: Format digest into atomic chunks (each under 3800 chars — never splits mid-URL)
    logger.info("Step 3: Formatting digest...")
    chunks = format_digest_chunks(ranked)
    logger.info(f"Digest split into {len(chunks)} message(s)")

    # Step 4: Send each chunk to Telegram
    logger.info("Step 4: Sending digest to Telegram...")
    all_ok = True
    for idx, chunk in enumerate(chunks):
        logger.info(f"Sending chunk {idx+1}/{len(chunks)} ({len(chunk)} chars)")
        ok = send_telegram_message(chunk)
        if not ok:
            all_ok = False
            logger.error(f"Chunk {idx+1} failed MarkdownV2, falling back to plain text")
            # Strip MarkdownV2 escapes for plain text fallback
            import re
            plain_chunk = re.sub(r'\\([_*\[\]()~`>#+=|{}.!-])', r'\1', chunk)
            send_telegram_message_plain(plain_chunk)

    if all_ok:
        logger.info("All digest chunks sent successfully!")
    else:
        logger.warning("Some chunks fell back to plain text.")

    # Step 5: Mark sent posts in DB so they won't repeat
    db.mark_sent(ranked)
    db.prune_sent_posts(keep_days=3)

    logger.info("Digest run complete.")


if __name__ == "__main__":
    run_digest()

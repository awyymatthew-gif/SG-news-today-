"""
db.py — Persistent SQLite database for SG News Bot.

All state that must survive restarts lives here:
  - sent_posts   : hashes of posts already sent (prevents duplicates)
  - users        : Telegram users who have interacted with the bot
  - listener_state : key/value store (e.g. Telegram update offset)

DB file location:
  Render persistent disk → /data/sgnews.db
  Local fallback         → ./sgnews.db
"""
import os
import sqlite3
import hashlib
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Path ──────────────────────────────────────────────────────────────────────
# Render mounts the persistent disk at /data.
# Locally we fall back to the project directory.
_DISK = "/data"
if os.path.isdir(_DISK) and os.access(_DISK, os.W_OK):
    DB_PATH = os.path.join(_DISK, "sgnews.db")
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sgnews.db")

logger.info(f"SQLite DB path: {DB_PATH}")


# ── Connection helper ─────────────────────────────────────────────────────────
def _conn():
    """Return a thread-safe SQLite connection with WAL mode enabled."""
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


# ── Schema bootstrap ──────────────────────────────────────────────────────────
def init_db():
    """Create tables if they don't exist. Safe to call on every startup."""
    with _conn() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS sent_posts (
                hash        TEXT PRIMARY KEY,
                title       TEXT,
                source      TEXT,
                sent_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                chat_id         TEXT PRIMARY KEY,
                username        TEXT,
                first_name      TEXT,
                first_seen      TEXT NOT NULL,
                last_seen       TEXT NOT NULL,
                message_count   INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS listener_state (
                key     TEXT PRIMARY KEY,
                value   TEXT NOT NULL
            );

            -- bot_state is an alias for listener_state (backward compat)
            CREATE TABLE IF NOT EXISTS bot_state (
                key     TEXT PRIMARY KEY,
                value   TEXT NOT NULL
            );
        """)
    logger.info("DB initialised.")


# ── sent_posts ────────────────────────────────────────────────────────────────
def _post_hash(post: dict) -> str:
    """Stable hash for a post based on title + source."""
    raw = (post.get("title", "") + "|" + post.get("source", "")).lower().strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_already_sent(post: dict) -> bool:
    """Return True if this post was already sent within the last 8 hours.

    8 hours prevents the same story repeating in back-to-back digests,
    while still allowing new stories that appear after a digest to be included.
    """
    h = _post_hash(post)
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM sent_posts WHERE hash=? AND sent_at > datetime('now', '-8 hours')",
            (h,)
        ).fetchone()
    return row is not None


def mark_sent(posts: list):
    """Record a list of posts as sent."""
    now = datetime.now(timezone.utc).isoformat()
    rows = [(_post_hash(p), p.get("title", "")[:200], p.get("source", "")[:100], now)
            for p in posts]
    with _conn() as con:
        con.executemany(
            "INSERT OR IGNORE INTO sent_posts (hash, title, source, sent_at) VALUES (?,?,?,?)",
            rows,
        )
    logger.info(f"Marked {len(rows)} posts as sent.")


def prune_sent_posts(keep_days: int = 3):
    """Delete sent_posts older than keep_days to keep the DB small."""
    with _conn() as con:
        con.execute(
            "DELETE FROM sent_posts WHERE sent_at < datetime('now', ?)",
            (f"-{keep_days} days",),
        )


# ── users ─────────────────────────────────────────────────────────────────────
def upsert_user(message: dict):
    """Insert or update a user record from a Telegram message dict."""
    from_data = message.get("from", {})
    chat_id   = str(message.get("chat", {}).get("id", ""))
    if not chat_id:
        return
    username   = from_data.get("username", "")
    first_name = from_data.get("first_name", "")
    now        = datetime.now(timezone.utc).isoformat()

    with _conn() as con:
        existing = con.execute(
            "SELECT first_seen, message_count FROM users WHERE chat_id=?", (chat_id,)
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE users
                   SET username=?, first_name=?, last_seen=?, message_count=message_count+1
                   WHERE chat_id=?""",
                (username, first_name, now, chat_id),
            )
        else:
            con.execute(
                """INSERT INTO users (chat_id, username, first_name, first_seen, last_seen, message_count)
                   VALUES (?,?,?,?,?,1)""",
                (chat_id, username, first_name, now, now),
            )


def get_all_users() -> list:
    """Return all users as a list of dicts."""
    with _conn() as con:
        rows = con.execute(
            "SELECT chat_id, username, first_name, first_seen, last_seen, message_count FROM users"
        ).fetchall()
    return [
        {
            "chat_id":       r[0],
            "username":      r[1],
            "first_name":    r[2],
            "first_seen":    r[3],
            "last_seen":     r[4],
            "message_count": r[5],
        }
        for r in rows
    ]


# ── listener_state ────────────────────────────────────────────────────────────
def get_state(key: str, default=None):
    """Get a value from the key/value state store."""
    with _conn() as con:
        row = con.execute("SELECT value FROM listener_state WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def set_state(key: str, value):
    """Set a value in the key/value state store."""
    with _conn() as con:
        con.execute(
            "INSERT OR REPLACE INTO listener_state (key, value) VALUES (?,?)",
            (key, str(value)),
        )

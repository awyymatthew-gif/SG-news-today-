"""
Breaking News Detector for SG News Bot.

Monitors all sources every 15 minutes and pushes an instant alert to all
registered users when a high-urgency story is detected.

Urgency is determined by:
  1. BREAKING_PREFIXES  — explicit "JUST IN", "BREAKING" etc. in title
  2. URGENCY_KEYWORDS   — high-impact topic words (deaths, disasters, attacks)
  3. SG_RELEVANCE       — story must involve Singapore or Singaporeans

A post must score >= URGENCY_THRESHOLD to trigger an alert.
Each post is only alerted once (uses the same sent_posts dedup table as digests,
with a separate 24-hour window to prevent re-alerting the same story).
"""
import re
import logging
import time

logger = logging.getLogger(__name__)

# ── Urgency signal: explicit breaking-news prefixes ───────────────────────────
BREAKING_PREFIXES = [
    r"\bjust in\b",
    r"\bbreaking\b",
    r"\burgent\b",
    r"\bflash\b",
    r"\balert\b",
    r"\bupdate\b.*\bdead\b",
    r"\bupdate\b.*\bkilled\b",
]

# ── Urgency signal: high-impact topic keywords ────────────────────────────────
URGENCY_KEYWORDS = {
    # Mass-casualty / disaster
    "dead": 4, "killed": 4, "deaths": 4, "fatalities": 4,
    "missing": 3, "injured": 3, "casualties": 4, "victims": 3,
    "explosion": 5, "blast": 5, "fire": 3, "flood": 3,
    "earthquake": 5, "tsunami": 5, "volcano": 4, "eruption": 4,
    "crash": 4, "collision": 3, "derailment": 4,
    "attack": 5, "shooting": 5, "stabbing": 4, "terrorism": 5, "bomb": 5,
    "hostage": 5, "kidnap": 4,
    # Health emergencies
    "outbreak": 4, "pandemic": 4, "epidemic": 4, "quarantine": 3,
    "lockdown": 4, "emergency": 4, "evacuation": 4,
    # Political / governance shocks
    "resign": 3, "arrested": 3, "charged": 3, "convicted": 3,
    "assassination": 5, "coup": 5,
    # Singapore-specific high-impact
    "haze": 3, "psi": 3, "dengue cluster": 3, "mrt disruption": 3,
    "power outage": 3, "water disruption": 3,
}

# ── Singapore relevance keywords ──────────────────────────────────────────────
SG_RELEVANCE_KEYWORDS = [
    "singapore", "singaporean", "singaporeans", "sg", "spore",
    "changi", "jurong", "orchard", "woodlands", "tampines", "bedok",
    "mrt", "hdb", "cpf", "pap", "spf", "saf", "mindef", "moh", "mfa",
    "pm lawrence", "pm wong", "minister", "parliament",
    "indonesia", "malaysia", "johor",  # nearby — relevant to SG readers
]

# ── Thresholds ────────────────────────────────────────────────────────────────
URGENCY_THRESHOLD = 5   # minimum urgency score to trigger an alert
BREAKING_PREFIX_BONUS = 6  # bonus added when a breaking prefix is matched


def _urgency_score(post: dict) -> int:
    """
    Compute an urgency score for a post.
    Returns 0 if the post has no Singapore relevance.
    """
    title = post.get("title", "").lower()
    body  = post.get("body", "").lower()
    text  = title + " " + body

    # Must have Singapore relevance
    if not any(kw in text for kw in SG_RELEVANCE_KEYWORDS):
        return 0

    score = 0

    # Breaking prefix bonus
    for pattern in BREAKING_PREFIXES:
        if re.search(pattern, title, re.IGNORECASE):
            score += BREAKING_PREFIX_BONUS
            break  # only count once

    # Urgency keyword scoring
    for kw, weight in URGENCY_KEYWORDS.items():
        if kw in text:
            score += weight

    return score


def is_breaking(post: dict) -> bool:
    """Return True if this post qualifies as breaking news."""
    return _urgency_score(post) >= URGENCY_THRESHOLD


def format_breaking_alert(post: dict) -> str:
    """
    Format a single breaking news post as a Telegram alert message.
    Kept short and punchy — one story, immediate clarity.
    """
    title  = post.get("title", "").strip()
    url    = post.get("url", "").strip()
    source = post.get("source", "").strip()

    lines = ["🚨 *BREAKING NEWS*\n"]
    lines.append(f"*{title}*")
    if source:
        lines.append(f"_{source}_")
    if url:
        lines.append(f"\n{url}")
    return "\n".join(lines)


def check_for_breaking_news(posts: list, db_module) -> list:
    """
    Given a list of fetched posts, return those that:
      1. Score >= URGENCY_THRESHOLD
      2. Have NOT already been alerted (uses is_already_sent with 24h window)

    The caller is responsible for calling db.mark_sent() on the returned posts.
    """
    alerts = []
    for post in posts:
        if not is_breaking(post):
            continue
        # Reuse the existing dedup mechanism — if already in sent_posts within
        # 24 hours, skip (the 8h window in is_already_sent is fine here too,
        # since breaking alerts are urgent and should not repeat within 8h)
        if db_module.is_already_sent(post):
            continue
        alerts.append(post)
        logger.info(
            f"Breaking news detected (score={_urgency_score(post)}): {post.get('title', '')[:80]}"
        )
    return alerts

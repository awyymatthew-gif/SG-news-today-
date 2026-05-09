"""
Breaking News Detector for SG News Bot.

Monitors all sources every 15 minutes and pushes an instant alert to all
registered users when a post shows a massive, sudden reaction spike.

SOLE TRIGGER — Reaction spike vs per-channel baseline:
  A post qualifies as breaking news if its reaction count is at least
  SPIKE_MULTIPLIER × the median reaction count of all other posts from
  the SAME channel in the current batch.

  This detects genuine audience shock/urgency (e.g. mass-casualty events,
  major disasters) without relying on keywords, which produce too many
  false positives.

  Additional guard: the post must have at least SPIKE_MIN_ABS reactions
  to avoid noise on low-engagement channels.

DEDUP — Two-layer deduplication:
  Layer 1 (exact):    db.is_already_sent() — title+source hash, 8-hour window
  Layer 2 (semantic): story_fingerprint() — normalised keyword set overlap.
    Checks BOTH:
      a) Within-batch: fingerprints of stories already queued this run
      b) Cross-batch:  fingerprints stored in DB from the last 8 hours
    Prevents the same event from alerting via multiple sources or via
    follow-up updates hours later.
"""
import re
import json
import logging
import statistics
from collections import defaultdict

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
# A post must have at least this many reactions to be considered at all.
SPIKE_MIN_ABS = 500

# A post must have at least this multiple of its channel's median to trigger.
# e.g. ST median ~430 → threshold ~2,150 reactions at 5x
# Mothership median ~750 → threshold ~3,750 reactions at 5x
SPIKE_MULTIPLIER = 5.0

# Semantic dedup
FINGERPRINT_OVERLAP_THRESHOLD = 3  # shared meaningful words = same story

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "its",
    "it", "this", "that", "these", "those", "after", "before", "during",
    "into", "over", "under", "about", "up", "out", "new", "more", "also",
    "says", "said", "say", "amid", "following", "including", "two", "three",
    "cna", "st", "straits", "times", "mothership", "hwz", "edmw",
    "one", "four", "five", "six", "seven", "eight", "nine", "ten",
})


# ── Per-channel baseline ──────────────────────────────────────────────────────

def _channel_medians(posts: list) -> dict:
    """
    Compute the median reaction count per channel from the current batch.
    Only considers posts from the same channel (Telegram source).
    Returns {source_string: median_float}.
    """
    by_channel = defaultdict(list)
    for p in posts:
        rxn = p.get("reactions", 0)
        if rxn > 0:
            by_channel[p.get("source", "")].append(rxn)

    medians = {}
    for ch, rxns in by_channel.items():
        if rxns:
            medians[ch] = statistics.median(rxns)
    return medians


def _is_reaction_spike(post: dict, channel_medians: dict) -> bool:
    """
    Return True if this post's reaction count is a significant spike above
    its own channel's median.
    """
    reactions = post.get("reactions", 0)
    if reactions < SPIKE_MIN_ABS:
        return False

    source = post.get("source", "")
    median = channel_medians.get(source, 0)
    if median <= 0:
        return False

    ratio = reactions / median
    if ratio >= SPIKE_MULTIPLIER:
        logger.info(
            f"Reaction spike detected: {reactions} reactions "
            f"({ratio:.1f}x median {median:.0f}) — {post.get('title', '')[:60]}"
        )
        return True
    return False


# ── Story fingerprinting (semantic dedup) ─────────────────────────────────────

def story_fingerprint(post: dict) -> frozenset:
    """
    Return a frozenset of meaningful words from the post title.
    Used to detect cross-source duplicates (same story, different outlet).
    """
    title = post.get("title", "").lower()
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    words = title.split()
    return frozenset(w for w in words if len(w) >= 4 and w not in _STOPWORDS)


def _stories_overlap(fp_a: frozenset, fp_b: frozenset) -> bool:
    """Return True if two story fingerprints share enough keywords."""
    if not fp_a or not fp_b:
        return False
    return len(fp_a & fp_b) >= FINGERPRINT_OVERLAP_THRESHOLD


def _get_recent_alert_fingerprints(db_module) -> list:
    """
    Retrieve story fingerprints of breaking alerts sent in the last 8 hours
    from the DB, for cross-batch semantic dedup.
    """
    try:
        raw = db_module.get_state("breaking_fingerprints_8h", "[]")
        stored = json.loads(raw)
        return [frozenset(fp) for fp in stored]
    except Exception:
        return []


def _save_alert_fingerprints(db_module, fingerprints: list):
    """Persist the current list of alerted story fingerprints to the DB."""
    try:
        serialisable = [list(fp) for fp in fingerprints]
        db_module.set_state("breaking_fingerprints_8h", json.dumps(serialisable))
    except Exception as e:
        logger.warning(f"Could not save breaking fingerprints: {e}")


# ── Public API ────────────────────────────────────────────────────────────────

def is_breaking(post: dict, channel_medians: dict = None) -> bool:
    """
    Return True if this post qualifies as breaking news.
    Pass channel_medians from the current batch for spike detection.
    """
    if channel_medians is None:
        channel_medians = {}
    return _is_reaction_spike(post, channel_medians)


def format_breaking_alert(post: dict) -> str:
    """
    Format a single breaking news post as a Telegram alert message.
    """
    title     = post.get("title", "").strip()
    url       = post.get("url", "").strip()
    source    = post.get("source", "").strip()
    reactions = post.get("reactions", 0)

    lines = ["🚨 *BREAKING NEWS*\n"]
    lines.append(f"*{title}*")
    if source:
        lines.append(f"_{source}_")
    if reactions:
        lines.append(f"_{reactions:,} reactions_")
    if url:
        lines.append(f"\n{url}")
    return "\n".join(lines)


def check_for_breaking_news(posts: list, db_module) -> list:
    """
    Given a list of fetched posts, return those that qualify as breaking news
    (reaction spike vs per-channel baseline).

    Three-layer dedup:
      1. db.is_already_sent()  — exact title+source hash (8-hour window)
      2. Within-batch semantic — fingerprint overlap with stories already
         queued in this run
      3. Cross-batch semantic  — fingerprint overlap with stories alerted
         in the last 8 hours

    The caller is responsible for calling db.mark_sent() on returned posts.
    """
    # Compute per-channel medians for spike detection
    medians = _channel_medians(posts)
    if medians:
        logger.debug(f"Channel medians: { {k: f'{v:.0f}' for k, v in medians.items()} }")

    # Load fingerprints from previous batches (cross-batch dedup)
    historical_fingerprints = _get_recent_alert_fingerprints(db_module)

    alerts = []
    alerted_fingerprints = list(historical_fingerprints)

    for post in posts:
        if not is_breaking(post, medians):
            continue

        # Layer 1: exact dedup
        if db_module.is_already_sent(post):
            continue

        # Layer 2 & 3: semantic dedup
        fp = story_fingerprint(post)
        if any(_stories_overlap(fp, prev_fp) for prev_fp in alerted_fingerprints):
            logger.info(
                f"Semantic dedup suppressed: "
                f"{post.get('source', '')} — {post.get('title', '')[:60]}"
            )
            continue

        alerted_fingerprints.append(fp)
        alerts.append(post)

    # Persist new fingerprints
    new_fps = alerted_fingerprints[len(historical_fingerprints):]
    if new_fps:
        _save_alert_fingerprints(db_module, alerted_fingerprints)

    return alerts

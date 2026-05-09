"""
Breaking News Detector for SG News Bot.

Monitors all sources every 15 minutes and pushes an instant alert to all
registered users when a high-urgency story is detected.

A post triggers an alert if it meets EITHER of two conditions:

  PATH A — Keyword urgency
    1. BREAKING_PREFIXES  — explicit "JUST IN", "BREAKING" etc. in title
    2. URGENCY_KEYWORDS   — high-impact topic words (deaths, disasters, attacks)
    3. SG_RELEVANCE       — story must involve Singapore or Singaporeans
    → score >= URGENCY_THRESHOLD

  PATH B — Reaction spike
    The post's reaction count is >= REACTION_SPIKE_MULTIPLIER × the median
    reaction count of all Telegram posts in the current batch.
    → reactions >= median * REACTION_SPIKE_MULTIPLIER AND reactions >= REACTION_MIN_ABS

DEDUP — Two-layer deduplication:
  Layer 1 (exact): db.is_already_sent() — title+source hash, 8-hour window
  Layer 2 (semantic): story_fingerprint() — normalised keyword set overlap.
    If a story with >= FINGERPRINT_OVERLAP_THRESHOLD shared keywords was already
    alerted in this batch, the duplicate is suppressed regardless of source.
    This prevents the same event (e.g. volcano eruption) from alerting once via
    ST Telegram and again via HWZ EDMW.
"""
import re
import logging
import statistics

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
    "haze": 3, "psi": 3,
    "disruption": 3,   # covers MRT/bus/power/water disruptions
    "outage": 3,       # power outage, water outage
    "dengue": 3,       # dengue cluster
}

# ── Singapore relevance keywords ──────────────────────────────────────────────
SG_RELEVANCE_KEYWORDS = [
    "singapore", "singaporean", "singaporeans", "sg", "spore",
    # Major towns / estates
    "changi", "jurong", "orchard", "woodlands", "tampines", "bedok",
    "toa payoh", "ang mo kio", "bishan", "clementi", "punggol", "sengkang",
    "yishun", "hougang", "pasir ris", "bukit timah", "novena", "geylang",
    "queenstown", "kallang", "marine parade", "buona vista",
    # Institutions / agencies
    "mrt", "hdb", "cpf", "pap", "spf", "saf", "mindef", "moh", "mfa",
    "scdf", "ica", "mas", "lta", "nea", "moe",
    "pm lawrence", "pm wong", "minister", "parliament",
    # Note: indonesia/malaysia/johor intentionally excluded — a story about
    # those countries only qualifies if it explicitly mentions Singaporeans.
]

# SG-specific locations/institutions that add +1 bonus to urgency score
# (helps borderline stories like MRT disruption or dengue cluster reach threshold)
SG_LOCATION_BONUS_KEYWORDS = [
    "singapore", "singaporean", "singaporeans",
    "changi", "jurong", "orchard", "woodlands", "tampines", "bedok",
    "toa payoh", "ang mo kio", "bishan", "clementi", "punggol", "sengkang",
    "yishun", "hougang", "pasir ris", "bukit timah", "novena",
    "mrt", "hdb", "spf", "saf", "cpf",
]

# ── Thresholds ────────────────────────────────────────────────────────────────
URGENCY_THRESHOLD = 4        # minimum keyword urgency score to trigger (Path A)
BREAKING_PREFIX_BONUS = 6    # bonus added when a breaking prefix is matched

# Path B — reaction spike
REACTION_SPIKE_MULTIPLIER = 2.5  # post must have >= 2.5x the batch median
REACTION_MIN_ABS = 300           # and at least 300 total reactions (avoids noise on small channels)

# Semantic dedup
FINGERPRINT_OVERLAP_THRESHOLD = 3  # shared meaningful words to consider same story
# Common words to ignore when fingerprinting
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "its",
    "it", "this", "that", "these", "those", "after", "before", "during",
    "into", "over", "under", "about", "up", "out", "new", "more", "also",
    "says", "said", "say", "amid", "amid", "following", "including",
    "cna", "st", "straits", "times", "mothership", "hwz", "edmw",
})


def story_fingerprint(post: dict) -> frozenset:
    """
    Return a frozenset of meaningful words from the post title.
    Used to detect cross-source duplicates (same story, different outlet).
    """
    title = post.get("title", "").lower()
    # Remove punctuation
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    words = title.split()
    # Keep words >= 4 chars that aren't stopwords
    return frozenset(w for w in words if len(w) >= 4 and w not in _STOPWORDS)


def _stories_overlap(fp_a: frozenset, fp_b: frozenset) -> bool:
    """Return True if two story fingerprints share enough keywords."""
    if not fp_a or not fp_b:
        return False
    return len(fp_a & fp_b) >= FINGERPRINT_OVERLAP_THRESHOLD


def _urgency_score(post: dict) -> int:
    """
    Compute a keyword-based urgency score for a post (Path A).
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

    # SG location/institution bonus: +1 if a specific SG place or body is named
    # This helps borderline stories (MRT disruption, dengue cluster) reach threshold
    if score > 0 and any(kw in text for kw in SG_LOCATION_BONUS_KEYWORDS):
        score += 1

    return score


def _reaction_spike(post: dict, median_reactions: float) -> bool:
    """
    Return True if this post's reaction count is a significant spike above
    the batch median (Path B).
    """
    reactions = post.get("reactions", 0)
    if reactions < REACTION_MIN_ABS:
        return False
    if median_reactions <= 0:
        return False
    return reactions >= median_reactions * REACTION_SPIKE_MULTIPLIER


def _batch_median_reactions(posts: list) -> float:
    """Compute the median reaction count across all Telegram posts in the batch."""
    counts = [p.get("reactions", 0) for p in posts if "reactions" in p]
    non_zero = [c for c in counts if c > 0]
    if not non_zero:
        return 0.0
    return statistics.median(non_zero)


def is_breaking(post: dict, median_reactions: float = 0.0) -> bool:
    """
    Return True if this post qualifies as breaking news via either path.
    Pass median_reactions from the current batch for Path B detection.
    """
    # Path A: keyword urgency
    if _urgency_score(post) >= URGENCY_THRESHOLD:
        return True
    # Path B: reaction spike
    if _reaction_spike(post, median_reactions):
        return True
    return False


def format_breaking_alert(post: dict, reason: str = "") -> str:
    """
    Format a single breaking news post as a Telegram alert message.
    Kept short and punchy — one story, immediate clarity.
    """
    title  = post.get("title", "").strip()
    url    = post.get("url", "").strip()
    source = post.get("source", "").strip()
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
    via either Path A (keyword urgency) or Path B (reaction spike).

    Two-layer dedup:
      1. db.is_already_sent()  — exact title+source hash (8-hour window)
      2. story_fingerprint()   — semantic overlap within this batch
         (prevents same event from alerting via multiple sources)

    The caller is responsible for calling db.mark_sent() on the returned posts.
    """
    # Compute batch median for Path B
    median_reactions = _batch_median_reactions(posts)
    if median_reactions > 0:
        logger.debug(f"Batch median reactions: {median_reactions:.0f}")

    alerts = []
    alerted_fingerprints = []  # fingerprints of stories already queued this batch

    for post in posts:
        if not is_breaking(post, median_reactions):
            continue

        # Layer 1: exact dedup via DB
        if db_module.is_already_sent(post):
            continue

        # Layer 2: semantic dedup within this batch
        fp = story_fingerprint(post)
        duplicate = any(_stories_overlap(fp, prev_fp) for prev_fp in alerted_fingerprints)
        if duplicate:
            logger.info(
                f"Semantic dedup suppressed cross-source duplicate: "
                f"{post.get('source', '')} — {post.get('title', '')[:60]}"
            )
            continue

        alerted_fingerprints.append(fp)
        alerts.append(post)

        score = _urgency_score(post)
        rxn   = post.get("reactions", 0)
        path  = "A(keywords)" if score >= URGENCY_THRESHOLD else f"B(reactions={rxn}, median={median_reactions:.0f})"
        logger.info(
            f"Breaking news [{path}]: {post.get('title', '')[:80]}"
        )

    return alerts

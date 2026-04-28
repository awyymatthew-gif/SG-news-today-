"""
Scoring and ranking engine for Singapore Ground Sense News Bot.

Source strategy:
- Reddit SG: boosted score so good posts naturally surface
- HWZ: only included if it crosses a high trending threshold (views/replies)
- Telegram channels: fill remaining slots based on raw score
- No forced slots — if Reddit has nothing worthy, Telegram fills the digest
"""
import time
import logging
from config import SCORE_WEIGHTS, TOP_N

logger = logging.getLogger(__name__)

# Keywords that boost relevance for Singapore ground-sense topics
SG_BOOST_KEYWORDS = [
    "singapore", "sg", "hdb", "cpf", "mrt", "pap", "wsg", "moh", "mas",
    "gst", "coe", "hawker", "singlish", "nsman", "ns", "poly", "ite",
    "jc", "psle", "o level", "a level", "pri school", "sec school",
    "cost of living", "housing", "rental", "property", "flat",
    "foreign worker", "pr", "citizen", "immigration",
    "election", "parliament", "minister", "pm", "dpm",
    "covid", "dengue", "haze", "flood",
    "scam", "fraud", "police", "spf", "ica",
    "grab", "foodpanda", "shopee", "lazada",
    "changi", "sentosa", "orchard", "jurong", "woodlands", "tampines",
]

# HWZ minimum thresholds to be considered "trending"
HWZ_MIN_VIEWS    = 5000   # thread views
HWZ_MIN_REPLIES  = 30     # thread replies

# Reddit scoring multiplier — boosts good Reddit posts to compete with Telegram
REDDIT_SCORE_MULTIPLIER = 2.5

# Soft cap: no single source group dominates more than this fraction of the digest
SOURCE_GROUP_MAX_FRACTION = 0.6   # e.g. CNA alone can't take more than 60% of slots


def _source_group(source):
    """Normalise a source into a broad group for diversity capping."""
    s = source.lower()
    if any(x in s for x in ["reddit", "r/singapore", "r/singaporeraw", "r/asksingapore"]):
        return "reddit"
    if any(x in s for x in ["hwz", "hardwarezone"]):
        return "hwz"
    if "cnalatest" in s or "cna" in s:
        return "cna"
    if "straitstimes" in s or "st" in s:
        return "st"
    if "todayonline" in s:
        return "today"
    if "govsg" in s or "gov.sg" in s:
        return "govsg"
    if "mothership" in s:
        return "mothership"
    return "other"


def compute_score(post):
    """Compute a relevance score for a post."""
    now = time.time()
    age_hours = max(0, (now - post.get("created_utc", now)) / 3600)

    raw_score = post.get("score", 0)
    comments  = post.get("comments", 0)

    # Base engagement score
    score = (
        raw_score * SCORE_WEIGHTS["upvotes"]
        + comments * SCORE_WEIGHTS["comments"]
        + age_hours * SCORE_WEIGHTS["recency_hours"]
    )

    # Singapore keyword relevance boost
    combined_text = (post.get("title", "") + " " + post.get("text", "")).lower()
    boost = sum(1 for kw in SG_BOOST_KEYWORDS if kw in combined_text)
    score += boost * 5

    source = post.get("source", "")
    group  = _source_group(source)

    # Reddit boost — good Reddit posts should naturally surface
    if group == "reddit":
        score *= REDDIT_SCORE_MULTIPLIER

    # Telegram channels: ensure they aren't buried when engagement signals are low
    if group in ("cna", "st", "today", "govsg", "mothership"):
        score = max(score, boost * 10)

    return round(score, 2)


def _is_hwz_trending(post):
    """Return True only if an HWZ post crosses the trending threshold."""
    views   = post.get("score", 0)    # HWZ uses 'score' field for view count
    replies = post.get("comments", 0)
    return views >= HWZ_MIN_VIEWS or replies >= HWZ_MIN_REPLIES


def deduplicate(posts):
    """Remove near-duplicate posts by title similarity (Jaccard > 0.7)."""
    seen_titles = []
    unique = []
    for post in posts:
        title = post.get("title", "").lower().strip()
        is_dup = False
        for seen in seen_titles:
            words_a = set(title.split())
            words_b = set(seen.split())
            if not words_a or not words_b:
                continue
            overlap = len(words_a & words_b) / len(words_a | words_b)
            if overlap > 0.7:
                is_dup = True
                break
        if not is_dup:
            unique.append(post)
            seen_titles.append(title)
    return unique


def rank_posts(posts):
    """Score, filter, deduplicate, and rank posts. Return top N."""
    if not posts:
        logger.warning("No posts to rank.")
        return []

    # Filter HWZ: only keep trending threads
    filtered = []
    hwz_dropped = 0
    for post in posts:
        if _source_group(post.get("source", "")) == "hwz":
            if _is_hwz_trending(post):
                filtered.append(post)
            else:
                hwz_dropped += 1
        else:
            filtered.append(post)

    if hwz_dropped:
        logger.info(f"Dropped {hwz_dropped} non-trending HWZ posts")

    # Score each post
    for post in filtered:
        post["computed_score"] = compute_score(post)

    # Deduplicate
    filtered = deduplicate(filtered)

    # Sort by score descending
    ranked = sorted(filtered, key=lambda x: x["computed_score"], reverse=True)

    # Soft diversity cap: no single source group takes more than SOURCE_GROUP_MAX_FRACTION
    max_per_group = max(1, int(TOP_N * SOURCE_GROUP_MAX_FRACTION))
    group_counts  = {}
    diverse = []
    overflow = []

    for post in ranked:
        g = _source_group(post.get("source", ""))
        if group_counts.get(g, 0) < max_per_group:
            diverse.append(post)
            group_counts[g] = group_counts.get(g, 0) + 1
        else:
            overflow.append(post)

    # Fill remaining slots with overflow posts (best scores first)
    result = diverse
    if len(result) < TOP_N:
        result += overflow[: TOP_N - len(result)]

    result = result[:TOP_N]

    # Log source breakdown
    breakdown = {}
    for post in result:
        g = _source_group(post.get("source", ""))
        breakdown[g] = breakdown.get(g, 0) + 1
    logger.info(f"Digest source breakdown: {breakdown}")

    return result

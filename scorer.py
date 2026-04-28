"""
Scoring and ranking engine for SG News Bot.

Variety matrix (15 slots total):
  CNA          3  — core hard news
  ST           2  — premium editorial
  Mothership   2  — lighter Gen Z-friendly SG news
  Reddit SG    2  — r/singapore ground sentiment
  Reddit Raw   1  — r/SingaporeRaw unfiltered opinions
  Reddit Ask   1  — r/askSingapore questions & advice
  Free         4  — best remaining posts by score from any source
  HWZ          0  — only if genuinely trending (high threshold)
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
HWZ_MIN_VIEWS   = 5000
HWZ_MIN_REPLIES = 30

# Reddit scoring multiplier
REDDIT_SCORE_MULTIPLIER = 2.5

# Variety matrix: guaranteed minimum slots per source group
# Total guaranteed = 11, free slots = 4, total = 15
VARIETY_MATRIX = {
    "cna":        3,   # Core hard news
    "st":         2,   # Premium editorial
    "mothership": 2,   # Gen Z-friendly SG news
    "reddit_sg":  2,   # r/singapore — ground sentiment
    "reddit_raw": 1,   # r/SingaporeRaw — unfiltered
    "reddit_ask": 1,   # r/askSingapore — questions & advice
    # 4 free slots filled by best remaining score (today/hwz can win here)
}
FREE_SLOTS = 4   # TOP_N - sum(VARIETY_MATRIX.values()) = 15 - 11 = 4


def _source_group(source):
    """Normalise a source string into a broad group key."""
    s = source.lower()
    if "r/singaporeraw" in s:
        return "reddit_raw"
    if "r/asksingapore" in s:
        return "reddit_ask"
    if any(x in s for x in ["r/singapore", "reddit"]):
        return "reddit_sg"
    if any(x in s for x in ["hwz", "hardwarezone"]):
        return "hwz"
    if "cnalatest" in s or s == "cna":
        return "cna"
    if "straitstimes" in s or s == "st":
        return "st"
    if "todayonline" in s or s == "today":
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

    score = (
        raw_score * SCORE_WEIGHTS["upvotes"]
        + comments * SCORE_WEIGHTS["comments"]
        + age_hours * SCORE_WEIGHTS["recency_hours"]
    )

    # Singapore keyword relevance boost
    combined_text = (post.get("title", "") + " " + post.get("text", "")).lower()
    boost = sum(1 for kw in SG_BOOST_KEYWORDS if kw in combined_text)
    score += boost * 5

    group = _source_group(post.get("source", ""))

    # Reddit boost
    if group in ("reddit_sg", "reddit_raw"):
        score *= REDDIT_SCORE_MULTIPLIER

    # Telegram/RSS channels: floor score so they aren't buried
    if group in ("cna", "st", "today", "mothership"):
        score = max(score, boost * 10)

    return round(score, 2)


def _is_hwz_trending(post):
    """Return True only if an HWZ post crosses the trending threshold."""
    views   = post.get("score", 0)
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
    """Score, filter, deduplicate, and rank posts using the variety matrix."""
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

    # --- Variety matrix selection ---
    # Build per-group pools (sorted by score)
    pools = {}
    for post in ranked:
        g = _source_group(post.get("source", ""))
        pools.setdefault(g, []).append(post)

    result = []

    # Fill guaranteed slots from each group
    for group, slots in VARIETY_MATRIX.items():
        pool = pools.get(group, [])
        taken = pool[:slots]
        result.extend(taken)

    # Fill free slots with best remaining posts not already selected
    selected_ids = {id(p) for p in result}
    remaining = [p for p in ranked if id(p) not in selected_ids]
    result.extend(remaining[:FREE_SLOTS])

    # If any group had fewer posts than guaranteed, fill with best remaining
    while len(result) < TOP_N:
        selected_ids = {id(p) for p in result}
        remaining = [p for p in ranked if id(p) not in selected_ids]
        if not remaining:
            break
        result.append(remaining[0])

    # Final sort by score for clean presentation
    result = sorted(result, key=lambda x: x.get("computed_score", 0), reverse=True)
    result = result[:TOP_N]

    # Log source breakdown
    breakdown = {}
    for post in result:
        g = _source_group(post.get("source", ""))
        breakdown[g] = breakdown.get(g, 0) + 1
    logger.info(f"Digest source breakdown: {breakdown}")

    return result

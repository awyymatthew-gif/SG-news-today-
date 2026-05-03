"""
Scoring and ranking engine for SG News Bot.

Variety matrix (15 slots total):
  CNA          4  — core hard news
  ST           3  — premium editorial
  Mothership   2  — lighter Gen Z-friendly SG news
  Today        1  — Today Online
  Free         5  — best remaining posts by score from any source
  HWZ          0  — only if genuinely trending (high threshold)

Note: Reddit removed — blocked on cloud servers (SSL/IP block).
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
# Total guaranteed = 10, free slots = 5, total = 15
# Reddit removed — blocked on cloud servers (SSL/IP block by Reddit CDN)
VARIETY_MATRIX = {
    "cna":        4,   # Core hard news
    "st":         3,   # Premium editorial
    "mothership": 2,   # Gen Z-friendly SG news
    "today":      1,   # Today Online
    # 5 free slots filled by best remaining score (hwz/other can win here)
}
FREE_SLOTS = 5   # TOP_N - sum(VARIETY_MATRIX.values()) = 15 - 10 = 5


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

    return round(float(score), 2)


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
    group_counts = {}  # tracks how many slots each group has taken

    # Step 1: Fill guaranteed slots from each group (hard cap = guaranteed)
    for group, slots in VARIETY_MATRIX.items():
        pool = pools.get(group, [])
        taken = pool[:slots]
        result.extend(taken)
        group_counts[group] = len(taken)

    # Step 2: Fill FREE_SLOTS with best remaining posts
    # First pass: each group wins at most 1 free slot (ensures variety)
    selected_ids = {id(p) for p in result}
    remaining = [p for p in ranked if id(p) not in selected_ids]
    free_added = 0
    free_group_counts = {}  # extra slots won per group in free slot pass
    for p in remaining:
        if free_added >= FREE_SLOTS:
            break
        g = _source_group(p.get("source", ""))
        if free_group_counts.get(g, 0) < 1:
            result.append(p)
            group_counts[g] = group_counts.get(g, 0) + 1
            free_group_counts[g] = free_group_counts.get(g, 0) + 1
            free_added += 1
    # Second pass: fill any remaining free slots with hard cap per group
    if free_added < FREE_SLOTS:
        selected_ids = {id(p) for p in result}
        remaining = [p for p in ranked if id(p) not in selected_ids]
        for p in remaining:
            if free_added >= FREE_SLOTS:
                break
            g = _source_group(p.get("source", ""))
            hard_cap = VARIETY_MATRIX.get(g, 0) + FREE_SLOTS
            if group_counts.get(g, 0) < hard_cap:
                result.append(p)
                group_counts[g] = group_counts.get(g, 0) + 1
                free_added += 1

    # Step 3: If result still short (some groups had 0 posts), fill with best remaining
    # Hard cap enforced: no group may exceed guaranteed + FREE_SLOTS
    while len(result) < TOP_N:
        selected_ids = {id(p) for p in result}
        remaining = [p for p in ranked if id(p) not in selected_ids]
        if not remaining:
            break
        added = False
        for p in remaining:
            g = _source_group(p.get("source", ""))
            hard_cap = VARIETY_MATRIX.get(g, 0) + FREE_SLOTS
            if group_counts.get(g, 0) < hard_cap:
                result.append(p)
                group_counts[g] = group_counts.get(g, 0) + 1
                added = True
                break
        if not added:
            # Truly no posts within cap — must overflow to avoid empty digest
            result.append(remaining[0])
            g = _source_group(remaining[0].get("source", ""))
            group_counts[g] = group_counts.get(g, 0) + 1
            break

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

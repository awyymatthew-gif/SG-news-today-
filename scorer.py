"""
Scoring and ranking engine for Singapore Ground Sense News Bot.
Scores posts based on engagement (upvotes/views, comments) and recency.
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


def compute_score(post):
    """Compute a relevance score for a post."""
    now = time.time()
    age_hours = max(0, (now - post.get("created_utc", now)) / 3600)

    raw_score = post.get("score", 0)
    comments = post.get("comments", 0)

    # Base score: weighted sum of engagement signals
    score = (
        raw_score * SCORE_WEIGHTS["upvotes"]
        + comments * SCORE_WEIGHTS["comments"]
        + age_hours * SCORE_WEIGHTS["recency_hours"]
    )

    # Keyword boost: check title and text for SG-relevant terms
    combined_text = (post.get("title", "") + " " + post.get("text", "")).lower()
    boost = sum(1 for kw in SG_BOOST_KEYWORDS if kw in combined_text)
    score += boost * 5

    # Source-based normalization: Telegram channels have fewer engagement signals
    source = post.get("source", "")
    if "Telegram" in source:
        score = max(score, boost * 10)  # Ensure Telegram posts aren't buried

    return round(score, 2)


def deduplicate(posts):
    """Remove near-duplicate posts by title similarity."""
    seen_titles = []
    unique = []
    for post in posts:
        title = post.get("title", "").lower().strip()
        # Simple dedup: skip if a very similar title already seen
        is_dup = False
        for seen in seen_titles:
            # Jaccard-like overlap on words
            words_a = set(title.split())
            words_b = set(seen.split())
            if len(words_a) == 0 or len(words_b) == 0:
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
    """Score, deduplicate, and rank posts. Return top N."""
    if not posts:
        logger.warning("No posts to rank.")
        return []

    # Score each post
    for post in posts:
        post["computed_score"] = compute_score(post)

    # Deduplicate
    posts = deduplicate(posts)

    # Sort by computed score descending
    ranked = sorted(posts, key=lambda x: x["computed_score"], reverse=True)

    logger.info(f"Ranked {len(ranked)} unique posts, returning top {TOP_N}")
    return ranked[:TOP_N]

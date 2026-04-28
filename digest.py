"""
Digest formatter for Singapore Ground Sense News Bot.
Generates a Telegram-formatted digest from ranked posts.
"""
import datetime
import pytz

SGT = pytz.timezone("Asia/Singapore")


def format_digest(ranked_posts):
    """Format ranked posts into a Telegram digest message."""
    now_sgt = datetime.datetime.now(SGT)
    timestamp = now_sgt.strftime("%d %b %Y, %I:%M %p SGT")

    lines = []
    lines.append(f"🇸🇬 *Singapore Ground Sense Digest*")
    lines.append(f"📅 {timestamp}")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━")
    lines.append("")

    if not ranked_posts:
        lines.append("_No significant posts found in the last 12 hours._")
        return "\n".join(lines)

    for i, post in enumerate(ranked_posts, 1):
        source = post.get("source", "Unknown")
        title = post.get("title", "No title").strip()
        url = post.get("url", "")
        score = post.get("computed_score", 0)
        raw_score = post.get("score", 0)
        comments = post.get("comments", 0)

        # Truncate long titles
        if len(title) > 200:
            title = title[:197] + "..."

        # Source emoji
        emoji = "📰"
        if "reddit" in source.lower() or source.startswith("r/"):
            emoji = "🔴"
        elif "hwz" in source.lower() or "hardwarezone" in source.lower():
            emoji = "💬"
        elif "telegram" in source.lower():
            emoji = "📢"

        # Format engagement stats
        stats_parts = []
        if raw_score > 0:
            stats_parts.append(f"⬆️{raw_score:,}")
        if comments > 0:
            stats_parts.append(f"💬{comments:,}")
        stats_str = "  ".join(stats_parts) if stats_parts else ""

        # Build entry
        if url:
            lines.append(f"{i}\\. {emoji} [{escape_md(title)}]({url})")
        else:
            lines.append(f"{i}\\. {emoji} {escape_md(title)}")

        lines.append(f"   📌 _{escape_md(source)}_  {stats_str}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"_Powered by SG Ground Sense Bot_")

    return "\n".join(lines)


def escape_md(text):
    """Escape MarkdownV2 special characters."""
    special_chars = r"\_*[]()~`>#+-=|{}.!"
    for ch in special_chars:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_digest_plain(ranked_posts):
    """Format ranked posts into a plain-text digest (fallback)."""
    now_sgt = datetime.datetime.now(SGT)
    timestamp = now_sgt.strftime("%d %b %Y, %I:%M %p SGT")

    lines = []
    lines.append(f"🇸🇬 Singapore Ground Sense Digest")
    lines.append(f"📅 {timestamp}")
    lines.append("=" * 40)
    lines.append("")

    if not ranked_posts:
        lines.append("No significant posts found in the last 12 hours.")
        return "\n".join(lines)

    for i, post in enumerate(ranked_posts, 1):
        source = post.get("source", "Unknown")
        title = post.get("title", "No title").strip()
        url = post.get("url", "")
        raw_score = post.get("score", 0)
        comments = post.get("comments", 0)

        if len(title) > 200:
            title = title[:197] + "..."

        lines.append(f"{i}. [{source}] {title}")
        if url:
            lines.append(f"   {url}")
        stats_parts = []
        if raw_score > 0:
            stats_parts.append(f"Score: {raw_score:,}")
        if comments > 0:
            stats_parts.append(f"Comments: {comments:,}")
        if stats_parts:
            lines.append(f"   {' | '.join(stats_parts)}")
        lines.append("")

    lines.append("=" * 40)
    lines.append("Powered by SG Ground Sense Bot")

    return "\n".join(lines)

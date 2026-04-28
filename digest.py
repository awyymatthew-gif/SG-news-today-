"""
Digest formatter for Singapore Ground Sense News Bot.
Clean, minimal format — headline + source, no noise.
"""
import datetime
import pytz

SGT = pytz.timezone("Asia/Singapore")

# Clean short source labels
SOURCE_LABELS = {
    "cnalatest":      "CNA",
    "cna":            "CNA",
    "todayonlinesg":  "Today",
    "straitstimes":   "ST",
    "govsg":          "Gov.sg",
    "mothership_sg":  "Mothership",
    "mothership":     "Mothership",
    "hwz":            "HWZ",
    "hardwarezone":   "HWZ",
    "r/singapore":    "Reddit SG",
    "r/singaporeraw": "Reddit SG",
    "r/asksingapore": "Reddit SG",
}

def short_source(source):
    """Return a clean short source label."""
    s = source.lower().strip()
    for key, label in SOURCE_LABELS.items():
        if key in s:
            return label
    # Fallback: capitalise first word
    return source.split()[0].title() if source else "SG"


def format_digest(ranked_posts):
    """Format ranked posts into a clean Telegram digest message."""
    now_sgt = datetime.datetime.now(SGT)
    hour = now_sgt.hour
    if 5 <= hour < 12:
        session = "Morning Digest"
    elif 12 <= hour < 17:
        session = "Midday Digest"
    else:
        session = "Evening Digest"

    date_str = now_sgt.strftime("%-d %b")

    lines = []
    lines.append(f"🇸🇬 *SG News — {session}*")
    lines.append(f"_{date_str}_")
    lines.append("")

    if not ranked_posts:
        lines.append("_Nothing significant in the last 12 hours._")
        return "\n".join(lines)

    for post in ranked_posts:
        source = post.get("source", "")
        title = post.get("title", "").strip()
        url = post.get("url", "")

        # Truncate at a natural sentence boundary or 180 chars
        if len(title) > 180:
            title = title[:177] + "…"

        label = short_source(source)

        if url:
            lines.append(f"[{escape_md(title)}]({url})")
        else:
            lines.append(f"*{escape_md(title)}*")

        lines.append(f"`{label}`")
        lines.append("")

    lines.append("─────────────────────")
    lines.append(f"_SG News Bot_")

    return "\n".join(lines)


def escape_md(text):
    """Escape MarkdownV2 special characters."""
    special_chars = r"\_*[]()~`>#+-=|{}.!"
    for ch in special_chars:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_digest_plain(ranked_posts):
    """Plain-text fallback digest."""
    now_sgt = datetime.datetime.now(SGT)
    date_str = now_sgt.strftime("%-d %b %Y, %-I:%M %p SGT")

    lines = []
    lines.append(f"🇸🇬 SG Ground Sense — {date_str}")
    lines.append("")

    if not ranked_posts:
        lines.append("Nothing significant in the last 12 hours.")
        return "\n".join(lines)

    for post in ranked_posts:
        source = post.get("source", "")
        title = post.get("title", "").strip()
        url = post.get("url", "")

        if len(title) > 180:
            title = title[:177] + "…"

        label = short_source(source)
        lines.append(f"• {title}")
        lines.append(f"  {label}" + (f"  {url}" if url else ""))
        lines.append("")

    lines.append("SG Ground Sense Bot")
    return "\n".join(lines)

"""
Digest formatter for SG News Bot.
Clean, minimal format — full headline + source label, no noise.
"""
import datetime
import pytz

SGT = pytz.timezone("Asia/Singapore")

# Clean short source labels — keyed on lowercase substrings of source field
SOURCE_LABELS = {
    "cnalatest":          "CNA",
    "cna":                "CNA",
    "todayonlinesg":      "Today",
    "thestraitstimes":    "ST",
    "straitstimes":       "ST",
    "govsg":              "Gov.sg",
    "mothershipsg":       "Mothership",
    "mothership_sg":      "Mothership",
    "mothership":         "Mothership",
    "hwz":                "HWZ",
    "hardwarezone":       "HWZ",
    "r/singapore":        "Reddit SG",
    "r/singaporeraw":     "Reddit Raw",
    "r/asksingapore":     "Ask SG",
}


def short_source(source):
    """Return a clean short source label."""
    s = source.lower().strip()
    for key, label in SOURCE_LABELS.items():
        if key in s:
            return label
    return source.split()[0].title() if source else "SG"


def escape_md(text):
    """Escape MarkdownV2 special characters."""
    special_chars = r"\_*[]()~`>#+-=|{}.!"
    for ch in special_chars:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_digest(ranked_posts):
    """Format ranked posts into a clean Telegram digest message (MarkdownV2)."""
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
        lines.append("_Nothing significant in the last 12 hours\\._")
        return "\n".join(lines)

    for post in ranked_posts:
        source = post.get("source", "")
        title = post.get("title", "").strip()
        url = post.get("url", "")

        # No truncation — use full title
        label = short_source(source)

        if url:
            lines.append(f"[{escape_md(title)}]({url})")
        else:
            lines.append(f"*{escape_md(title)}*")

        lines.append(f"`{label}`")
        lines.append("")

    lines.append("─────────────────────")
    lines.append("_SG News Bot_")

    return "\n".join(lines)


def format_digest_plain(ranked_posts):
    """Plain-text fallback digest (used if MarkdownV2 send fails)."""
    now_sgt = datetime.datetime.now(SGT)
    date_str = now_sgt.strftime("%-d %b %Y, %-I:%M %p SGT")

    lines = []
    lines.append(f"🇸🇬 SG News — {date_str}")
    lines.append("")

    if not ranked_posts:
        lines.append("Nothing significant in the last 12 hours.")
        return "\n".join(lines)

    for post in ranked_posts:
        source = post.get("source", "")
        title = post.get("title", "").strip()
        url = post.get("url", "")

        label = short_source(source)
        lines.append(f"• {title}")
        lines.append(f"  {label}" + (f"  {url}" if url else ""))
        lines.append("")

    lines.append("SG News Bot")
    return "\n".join(lines)

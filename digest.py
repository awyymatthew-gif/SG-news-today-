"""
Digest formatter for SG News Bot.
Clean, minimal format — full headline + source label, no noise.
Sends in multiple messages if needed to avoid Telegram's 4096-char limit.
"""
import datetime
import pytz

SGT = pytz.timezone("Asia/Singapore")

# Telegram hard limit is 4096 chars; use 3800 as safe ceiling per message
MAX_MSG_LEN = 3800

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


def _session_label(now_sgt):
    hour = now_sgt.hour
    if 5 <= hour < 12:
        return "Morning Digest"
    elif 12 <= hour < 17:
        return "Midday Digest"
    else:
        return "Evening Digest"


def format_digest_chunks(ranked_posts):
    """
    Return a list of MarkdownV2 message strings, each under MAX_MSG_LEN chars.
    The header is on the first message, footer on the last.
    Each post is kept atomic — never split mid-post.
    """
    now_sgt = datetime.datetime.now(SGT)
    session = _session_label(now_sgt)
    date_str = now_sgt.strftime("%-d %b")

    header = f"🇸🇬 *SG News — {session}*\n_{date_str}_\n\n"
    footer = "\n─────────────────────\n_SG News Bot_"

    if not ranked_posts:
        return [header + "_Nothing significant in the last 12 hours\\._" + footer]

    # Build one atomic block per post
    post_blocks = []
    for post in ranked_posts:
        source = post.get("source", "")
        title = post.get("title", "").strip()
        url = post.get("url", "")
        label = short_source(source)
        escaped_title = escape_md(title)

        if url:
            line = f"[{escaped_title}]({url})"
        else:
            line = f"*{escaped_title}*"

        block = f"{line}\n`{label}`\n"
        post_blocks.append(block)

    # Pack blocks into messages respecting MAX_MSG_LEN
    messages = []
    current_blocks = []
    # First message starts with header
    current_len = len(header)

    for i, block in enumerate(post_blocks):
        block_len = len(block) + 1  # +1 for joining newline
        is_last = (i == len(post_blocks) - 1)
        footer_reserve = len(footer) if is_last else 0

        if current_blocks and (current_len + block_len + footer_reserve > MAX_MSG_LEN):
            # Flush current message without footer (more blocks coming)
            prefix = header if not messages else ""
            messages.append(prefix + "\n".join(current_blocks))
            current_blocks = [block]
            current_len = block_len
        else:
            current_blocks.append(block)
            current_len += block_len

    # Flush final message with footer
    if current_blocks:
        prefix = header if not messages else ""
        messages.append(prefix + "\n".join(current_blocks) + footer)

    return messages


def format_digest(ranked_posts):
    """
    Returns the first chunk only (for backward compatibility with tests).
    Use format_digest_chunks() for actual sending.
    """
    chunks = format_digest_chunks(ranked_posts)
    return chunks[0] if chunks else ""


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

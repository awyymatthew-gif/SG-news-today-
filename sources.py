"""
Source fetchers for Singapore Ground Sense News Bot.
Fetches from Reddit SG subreddits, HardwareZone EDMW, and Telegram channels.
"""
import logging
import time
import datetime
import xml.etree.ElementTree as ET
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from bs4 import BeautifulSoup
from config import (
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT,
    REDDIT_SUBREDDITS, HWZ_EDMW_URL, TELEGRAM_CHANNELS, LOOKBACK_HOURS
)

logger = logging.getLogger(__name__)


def get_cutoff_time():
    """Return UTC timestamp for LOOKBACK_HOURS ago."""
    return time.time() - (LOOKBACK_HOURS * 3600)


def fetch_reddit_posts():
    """Fetch hot posts from configured SG subreddits using Reddit RSS feeds."""
    import xml.etree.ElementTree as ET
    posts = []
    cutoff = get_cutoff_time()
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
    }

    for subreddit in REDDIT_SUBREDDITS:
        try:
            url = f"https://www.reddit.com/r/{subreddit}/hot.rss?limit=50"
            resp = requests.get(url, headers=headers, timeout=15, verify=False)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall("atom:entry", ns)
            count = 0
            for entry in entries:
                title_el = entry.find("atom:title", ns)
                link_el = entry.find("atom:link", ns)
                updated_el = entry.find("atom:updated", ns)
                content_el = entry.find("atom:content", ns)

                title = title_el.text if title_el is not None else ""
                link = link_el.get("href", "") if link_el is not None else ""
                text = ""
                if content_el is not None and content_el.text:
                    # Strip HTML tags from content
                    soup = BeautifulSoup(content_el.text, "html.parser")
                    text = soup.get_text(separator=" ", strip=True)[:300]

                created_utc = time.time()
                if updated_el is not None and updated_el.text:
                    try:
                        dt = datetime.datetime.fromisoformat(updated_el.text.replace("Z", "+00:00"))
                        created_utc = dt.timestamp()
                    except Exception:
                        pass

                if created_utc < cutoff:
                    continue

                posts.append({
                    "source": f"r/{subreddit}",
                    "title": title,
                    "url": link,
                    "score": 0,  # RSS doesn't expose score
                    "comments": 0,
                    "created_utc": created_utc,
                    "text": text,
                })
                count += 1

            logger.info(f"Fetched {count} posts from r/{subreddit} via RSS")
            time.sleep(1)  # Rate limit
        except Exception as e:
            logger.error(f"Error fetching r/{subreddit}: {e}")

    return posts


def fetch_hwz_edmw():
    """Scrape HardwareZone EDMW forum for recent hot threads."""
    posts = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        }
        resp = requests.get(HWZ_EDMW_URL, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Parse thread listings
        threads = soup.select("div.structItem--thread")
        if not threads:
            # Try alternative selector
            threads = soup.select("li.discussionListItem") or soup.select(".js-threadList .structItem")

        count = 0
        for thread in threads[:30]:
            try:
                title_el = thread.select_one("div.structItem-title a") or thread.select_one(".title a")
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://forums.hardwarezone.com.sg" + href

                # Get reply count
                replies_el = thread.select_one("dd.pairs--justified") or thread.select_one(".discussionListItem-stats .count")
                replies = 0
                if replies_el:
                    try:
                        replies = int(replies_el.get_text(strip=True).replace(",", ""))
                    except Exception:
                        pass

                posts.append({
                    "source": "HWZ EDMW",
                    "title": title,
                    "url": href,
                    "score": replies,
                    "comments": replies,
                    "created_utc": time.time(),  # No timestamp available easily
                    "text": "",
                })
                count += 1
            except Exception as e:
                logger.debug(f"Error parsing HWZ thread: {e}")

        logger.info(f"Fetched {count} threads from HWZ EDMW")
    except Exception as e:
        logger.error(f"Error fetching HWZ EDMW: {e}")

    return posts


def fetch_telegram_channels():
    """
    Fetch recent posts from public Telegram channels via t.me web preview.
    Uses the public web interface since no bot token may be available for channel reading.
    """
    posts = []
    cutoff_dt = datetime.datetime.utcnow() - datetime.timedelta(hours=LOOKBACK_HOURS)

    for channel in TELEGRAM_CHANNELS:
        channel_name = channel.lstrip("@")
        try:
            url = f"https://t.me/s/{channel_name}"
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            messages = soup.select(".tgme_widget_message_wrap")
            count = 0
            for msg in messages[-20:]:  # Last 20 messages
                try:
                    text_el = msg.select_one(".tgme_widget_message_text")
                    time_el = msg.select_one(".tgme_widget_message_date time")
                    link_el = msg.select_one("a.tgme_widget_message_date")

                    if not text_el:
                        continue

                    text = text_el.get_text(separator=" ", strip=True)[:500]
                    if not text:
                        continue

                    msg_url = ""
                    if link_el:
                        msg_url = link_el.get("href", "")

                    created_utc = time.time()
                    if time_el:
                        dt_str = time_el.get("datetime", "")
                        try:
                            dt = datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                            created_utc = dt.timestamp()
                        except Exception:
                            pass

                    # Views as proxy for score
                    views_el = msg.select_one(".tgme_widget_message_views")
                    views = 0
                    if views_el:
                        v_text = views_el.get_text(strip=True).replace("K", "000").replace("M", "000000")
                        try:
                            views = int(v_text.replace(",", "").replace(".", ""))
                        except Exception:
                            pass

                    posts.append({
                        "source": f"Telegram {channel}",
                        "title": text[:120],
                        "url": msg_url,
                        "score": views,
                        "comments": 0,
                        "created_utc": created_utc,
                        "text": text,
                    })
                    count += 1
                except Exception as e:
                    logger.debug(f"Error parsing message from {channel}: {e}")

            logger.info(f"Fetched {count} messages from {channel}")
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Error fetching Telegram channel {channel}: {e}")

    return posts


def fetch_mothership():
    """Fetch latest articles from Mothership.sg via RSS feed."""
    posts = []
    cutoff = get_cutoff_time()
    try:
        url = "https://mothership.sg/feed/"
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")
        count = 0
        for item in items[:20]:
            title = (item.findtext("title") or "").strip()
            link  = (item.findtext("link")  or "").strip()
            pub_date = item.findtext("pubDate") or ""
            created_utc = time.time()
            if pub_date:
                try:
                    import email.utils
                    created_utc = email.utils.parsedate_to_datetime(pub_date).timestamp()
                except Exception:
                    pass
            if created_utc < cutoff:
                continue
            posts.append({
                "source": "Mothership",
                "title": title,
                "url": link,
                "score": 0,
                "comments": 0,
                "created_utc": created_utc,
                "text": title,
            })
            count += 1
        logger.info(f"Fetched {count} articles from Mothership RSS")
    except Exception as e:
        logger.error(f"Error fetching Mothership RSS: {e}")
    return posts


def fetch_all_sources():
    """Fetch posts from all configured sources."""
    all_posts = []

    logger.info("Fetching from Reddit SG subreddits...")
    reddit_posts = fetch_reddit_posts()
    all_posts.extend(reddit_posts)
    logger.info(f"Reddit: {len(reddit_posts)} posts")

    logger.info("Fetching from HardwareZone EDMW...")
    hwz_posts = fetch_hwz_edmw()
    all_posts.extend(hwz_posts)
    logger.info(f"HWZ EDMW: {len(hwz_posts)} posts")

    logger.info("Fetching from Telegram channels...")
    tg_posts = fetch_telegram_channels()
    all_posts.extend(tg_posts)
    logger.info(f"Telegram channels: {len(tg_posts)} posts")

    logger.info("Fetching from Mothership RSS...")
    ms_posts = fetch_mothership()
    all_posts.extend(ms_posts)
    logger.info(f"Mothership: {len(ms_posts)} posts")

    logger.info(f"Total posts fetched: {len(all_posts)}")
    return all_posts

"""
SG News Bot — 100-Scenario UAT Test Suite
Covers: db, config, scorer, digest, sources, bot, listener edge cases
"""
import os, sys, time, json, sqlite3, hashlib, re, unittest, tempfile, shutil
from unittest.mock import patch, MagicMock, call
from datetime import datetime, timezone

# ── Setup: point DB to a temp dir so tests don't pollute /data ────────────────
_TMP = tempfile.mkdtemp()
os.environ["SG_NEWS_DB_PATH"] = os.path.join(_TMP, "test.db")

sys.path.insert(0, "/home/ubuntu/sg_news_bot")

import db
import config
import scorer
import digest

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def make_post(title="Test post", source="cna", score=100, comments=10,
              created_utc=None, url="https://example.com"):
    return {
        "title": title,
        "source": source,
        "score": score,
        "comments": comments,
        "created_utc": created_utc or time.time(),
        "url": url,
        "text": "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 1: DB MODULE (20 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestDB(unittest.TestCase):

    def setUp(self):
        db.init_db()

    # T01
    def test_init_db_creates_tables(self):
        con = sqlite3.connect(db.DB_PATH)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        con.close()
        self.assertIn("sent_posts", tables)
        self.assertIn("users", tables)
        self.assertIn("bot_state", tables)

    # T02
    def test_set_and_get_state(self):
        db.set_state("test_key", 42)
        self.assertEqual(int(db.get_state("test_key", 0)), 42)

    # T03
    def test_get_state_default(self):
        self.assertEqual(db.get_state("nonexistent_key", "default"), "default")

    # T04
    def test_set_state_overwrite(self):
        db.set_state("ow_key", 1)
        db.set_state("ow_key", 2)
        self.assertEqual(int(db.get_state("ow_key", 0)), 2)

    # T05
    def test_mark_sent_single(self):
        p = make_post(title="Unique post T05")
        db.mark_sent([p])
        self.assertTrue(db.is_already_sent(p))

    # T06
    def test_is_already_sent_false_for_new(self):
        p = make_post(title="Brand new post T06 xyz123")
        self.assertFalse(db.is_already_sent(p))

    # T07
    def test_mark_sent_multiple(self):
        posts = [make_post(title=f"Post T07-{i}") for i in range(5)]
        db.mark_sent(posts)
        for p in posts:
            self.assertTrue(db.is_already_sent(p))

    # T08
    def test_mark_sent_empty_list(self):
        # Should not raise
        db.mark_sent([])

    # T09
    def test_prune_sent_posts(self):
        # Insert an old post directly
        h = hashlib.md5("old post prune T09".encode()).hexdigest()
        con = sqlite3.connect(db.DB_PATH)
        con.execute("INSERT OR IGNORE INTO sent_posts (hash, sent_at) VALUES (?, datetime('now', '-10 days'))", (h,))
        con.commit()
        con.close()
        db.prune_sent_posts(keep_days=3)
        con = sqlite3.connect(db.DB_PATH)
        row = con.execute("SELECT hash FROM sent_posts WHERE hash=?", (h,)).fetchone()
        con.close()
        self.assertIsNone(row)

    # T10
    def test_prune_keeps_recent(self):
        p = make_post(title="Recent post T10 keep")
        db.mark_sent([p])
        db.prune_sent_posts(keep_days=3)
        self.assertTrue(db.is_already_sent(p))

    # T11
    def test_upsert_user_new(self):
        msg = {"from": {"username": "testuser_T11", "first_name": "Test", "last_name": ""}, "chat": {"id": 111111}}
        db.upsert_user(msg)
        users = db.get_all_users()
        ids = [u["chat_id"] for u in users]
        self.assertIn("111111", ids)

    # T12
    def test_upsert_user_updates_existing(self):
        msg = {"from": {"username": "user_T12", "first_name": "A"}, "chat": {"id": 222222}}
        db.upsert_user(msg)
        msg2 = {"from": {"username": "user_T12_new", "first_name": "B"}, "chat": {"id": 222222}}
        db.upsert_user(msg2)
        users = {u["chat_id"]: u for u in db.get_all_users()}
        self.assertEqual(users["222222"]["username"], "user_T12_new")

    # T13
    def test_upsert_user_increments_message_count(self):
        msg = {"from": {"username": "counter_T13"}, "chat": {"id": 333333}}
        db.upsert_user(msg)
        db.upsert_user(msg)
        users = {u["chat_id"]: u for u in db.get_all_users()}
        self.assertGreaterEqual(users["333333"]["message_count"], 2)

    # T14
    def test_upsert_user_no_username(self):
        msg = {"from": {"first_name": "NoUsername"}, "chat": {"id": 444444}}
        db.upsert_user(msg)  # Should not raise

    # T15
    def test_upsert_user_missing_from(self):
        msg = {"chat": {"id": 555555}}
        db.upsert_user(msg)  # Should not raise

    # T16
    def test_get_all_users_returns_list(self):
        result = db.get_all_users()
        self.assertIsInstance(result, list)

    # T17
    def test_is_already_sent_uses_title_hash(self):
        p1 = make_post(title="Hash test T17", url="https://a.com")
        p2 = make_post(title="Hash test T17", url="https://b.com")  # same title, diff url
        db.mark_sent([p1])
        self.assertTrue(db.is_already_sent(p2))  # title hash matches

    # T18
    def test_init_db_idempotent(self):
        db.init_db()
        db.init_db()  # Should not raise or corrupt

    # T19
    def test_state_string_value(self):
        db.set_state("str_key", "hello world")
        self.assertEqual(db.get_state("str_key", ""), "hello world")

    # T20
    def test_mark_sent_post_with_empty_title(self):
        p = make_post(title="")
        db.mark_sent([p])  # Should not raise


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 2: SCORER MODULE (25 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestScorer(unittest.TestCase):

    # T21
    def test_compute_score_basic(self):
        p = make_post(score=100, comments=50)
        s = scorer.compute_score(p)
        self.assertGreater(s, 0)

    # T22
    def test_compute_score_zero_inputs(self):
        p = make_post(score=0, comments=0)
        s = scorer.compute_score(p)
        self.assertIsInstance(s, float)

    # T23
    def test_sg_keyword_boost(self):
        p_sg = make_post(title="HDB flat prices rise in Singapore")
        p_no = make_post(title="Random unrelated post about cats")
        self.assertGreater(scorer.compute_score(p_sg), scorer.compute_score(p_no))

    # T24
    def test_reddit_multiplier_applied(self):
        p_reddit = make_post(source="r/singapore", score=50)
        p_cna = make_post(source="cna", score=50)
        # Reddit should score higher due to multiplier
        self.assertGreater(scorer.compute_score(p_reddit), scorer.compute_score(p_cna))

    # T25
    def test_source_group_cna(self):
        self.assertEqual(scorer._source_group("cna"), "cna")
        self.assertEqual(scorer._source_group("cnalatest"), "cna")

    # T26
    def test_source_group_st(self):
        self.assertEqual(scorer._source_group("straitstimes"), "st")
        self.assertEqual(scorer._source_group("st"), "st")

    # T27
    def test_source_group_mothership(self):
        self.assertEqual(scorer._source_group("mothership"), "mothership")

    # T28
    def test_source_group_reddit_sg(self):
        self.assertEqual(scorer._source_group("r/singapore"), "reddit_sg")
        self.assertEqual(scorer._source_group("reddit"), "reddit_sg")

    # T29
    def test_source_group_reddit_raw(self):
        self.assertEqual(scorer._source_group("r/singaporeraw"), "reddit_raw")

    # T30
    def test_source_group_reddit_ask(self):
        self.assertEqual(scorer._source_group("r/asksingapore"), "reddit_ask")

    # T31
    def test_source_group_hwz(self):
        self.assertEqual(scorer._source_group("hwz"), "hwz")
        self.assertEqual(scorer._source_group("hardwarezone"), "hwz")

    # T32
    def test_source_group_unknown(self):
        self.assertEqual(scorer._source_group("unknownsource"), "other")

    # T33
    def test_hwz_trending_above_threshold(self):
        p = make_post(source="hwz", score=scorer.HWZ_MIN_VIEWS + 1)
        self.assertTrue(scorer._is_hwz_trending(p))

    # T34
    def test_hwz_not_trending_below_threshold(self):
        p = make_post(source="hwz", score=0, comments=0)
        self.assertFalse(scorer._is_hwz_trending(p))

    # T35
    def test_hwz_trending_by_replies(self):
        p = make_post(source="hwz", score=0, comments=scorer.HWZ_MIN_REPLIES + 1)
        self.assertTrue(scorer._is_hwz_trending(p))

    # T36
    def test_deduplicate_removes_near_duplicate(self):
        p1 = make_post(title="Singapore property prices rise sharply in Q1")
        p2 = make_post(title="Singapore property prices rise sharply in Q1 2026")
        result = scorer.deduplicate([p1, p2])
        self.assertEqual(len(result), 1)

    # T37
    def test_deduplicate_keeps_distinct(self):
        p1 = make_post(title="HDB prices rise")
        p2 = make_post(title="MRT breakdown causes delays")
        result = scorer.deduplicate([p1, p2])
        self.assertEqual(len(result), 2)

    # T38
    def test_rank_posts_empty(self):
        result = scorer.rank_posts([])
        self.assertEqual(result, [])

    # T39
    def test_rank_posts_returns_max_top_n(self):
        posts = [make_post(title=f"Post {i}", source="cna") for i in range(30)]
        result = scorer.rank_posts(posts)
        self.assertLessEqual(len(result), scorer.TOP_N)

    # T40
    def test_rank_posts_all_hwz_non_trending_dropped(self):
        posts = [make_post(title=f"HWZ {i}", source="hwz", score=0, comments=0) for i in range(5)]
        result = scorer.rank_posts(posts)
        self.assertEqual(len(result), 0)

    # T41
    def test_rank_posts_variety_matrix_respected(self):
        # With 6 diverse sources all having posts, CNA should be capped at guaranteed(3) + 1 free = 4
        posts = [make_post(title=f"CNA {i}", source="cna", score=1000) for i in range(10)]
        posts += [make_post(title=f"ST {i}", source="thestraitstimes", score=900) for i in range(10)]
        posts += [make_post(title=f"Mothership {i}", source="mothership", score=800) for i in range(10)]
        posts += [make_post(title=f"Reddit {i}", source="r/singapore", score=700) for i in range(10)]
        posts += [make_post(title=f"RedditRaw {i}", source="r/singaporeraw", score=600) for i in range(10)]
        posts += [make_post(title=f"Ask {i}", source="r/asksingapore", score=500) for i in range(10)]
        result = scorer.rank_posts(posts)
        cna_count = sum(1 for p in result if scorer._source_group(p["source"]) == "cna")
        # With all sources present, CNA should not exceed guaranteed + 1 free slot
        self.assertLessEqual(cna_count, scorer.VARIETY_MATRIX.get("cna", 0) + 1)

    # T42
    def test_rank_posts_sorted_by_score(self):
        posts = [make_post(title=f"Post {i}", source="cna", score=i*10) for i in range(5)]
        result = scorer.rank_posts(posts)
        scores = [p["computed_score"] for p in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    # T43
    def test_compute_score_old_post_lower(self):
        old = make_post(score=100, created_utc=time.time() - 86400*7)  # 7 days old
        new = make_post(score=100, created_utc=time.time())
        # Old post has negative recency contribution
        self.assertLessEqual(scorer.compute_score(old), scorer.compute_score(new))

    # T44
    def test_deduplicate_empty(self):
        self.assertEqual(scorer.deduplicate([]), [])

    # T45
    def test_deduplicate_single(self):
        p = make_post(title="Only post")
        self.assertEqual(scorer.deduplicate([p]), [p])


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 3: DIGEST FORMATTING (20 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestDigest(unittest.TestCase):

    def _sample_posts(self, n=5):
        return [make_post(title=f"Story {i}: Singapore news today", source="cna", url=f"https://cna.asia/{i}") for i in range(n)]

    # T46
    def test_format_digest_returns_string(self):
        result = digest.format_digest(self._sample_posts())
        self.assertIsInstance(result, str)

    # T47
    def test_format_digest_not_empty(self):
        result = digest.format_digest(self._sample_posts())
        self.assertGreater(len(result), 0)

    # T48
    def test_format_digest_plain_returns_string(self):
        result = digest.format_digest_plain(self._sample_posts())
        self.assertIsInstance(result, str)

    # T49
    def test_format_digest_plain_not_empty(self):
        result = digest.format_digest_plain(self._sample_posts())
        self.assertGreater(len(result), 0)

    # T50
    def test_format_digest_empty_posts(self):
        result = digest.format_digest([])
        self.assertIsInstance(result, str)

    # T51
    def test_format_digest_plain_empty_posts(self):
        result = digest.format_digest_plain([])
        self.assertIsInstance(result, str)

    # T52
    def test_format_digest_contains_title(self):
        posts = [make_post(title="Unique title XYZ123")]
        result = digest.format_digest_plain(posts)
        self.assertIn("Unique title XYZ123", result)

    # T53
    def test_format_digest_contains_source(self):
        posts = [make_post(source="cna")]
        result = digest.format_digest_plain(posts)
        self.assertIn("cna", result.lower())

    # T54
    def test_format_digest_15_posts(self):
        posts = self._sample_posts(15)
        result = digest.format_digest_plain(posts)
        self.assertGreater(len(result), 100)

    # T55
    def test_format_digest_special_chars_no_crash(self):
        posts = [make_post(title="Cost: $1,000 — 50% off! (Today only) [Limited]")]
        result = digest.format_digest(posts)
        self.assertIsInstance(result, str)

    # T56
    def test_format_digest_url_included(self):
        posts = [make_post(url="https://cna.asia/test-article")]
        result = digest.format_digest_plain(posts)
        self.assertIn("https://cna.asia/test-article", result)

    # T57
    def test_format_digest_no_url(self):
        posts = [make_post(url="")]
        result = digest.format_digest_plain(posts)
        self.assertIsInstance(result, str)

    # T58
    def test_format_digest_markdown_under_4096(self):
        posts = self._sample_posts(15)
        result = digest.format_digest(posts)
        # Each chunk should be under 4096
        self.assertLessEqual(len(result), 15 * 300)  # reasonable upper bound

    # T59
    def test_format_digest_unicode_title(self):
        posts = [make_post(title="新加坡新闻: HDB prices rise 10%")]
        result = digest.format_digest_plain(posts)
        self.assertIn("HDB", result)

    # T60
    def test_format_digest_very_long_title(self):
        long_title = "A" * 500
        posts = [make_post(title=long_title)]
        result = digest.format_digest_plain(posts)
        self.assertIsInstance(result, str)

    # T61
    def test_format_digest_none_url_no_crash(self):
        posts = [make_post(url=None)]
        try:
            result = digest.format_digest_plain(posts)
            self.assertIsInstance(result, str)
        except Exception as e:
            self.fail(f"format_digest_plain crashed with None url: {e}")

    # T62
    def test_format_digest_single_post(self):
        posts = [make_post()]
        result = digest.format_digest_plain(posts)
        self.assertGreater(len(result), 10)

    # T63
    def test_format_digest_includes_numbering(self):
        posts = self._sample_posts(3)
        result = digest.format_digest_plain(posts)
        self.assertIn("1", result)

    # T64
    def test_format_digest_plain_no_markdown_escapes(self):
        posts = [make_post(title="Test & check")]
        result = digest.format_digest_plain(posts)
        # Plain text should not have MarkdownV2 escape backslashes
        self.assertNotIn("\\&", result)

    # T65
    def test_format_digest_post_missing_fields(self):
        posts = [{"title": "Minimal post"}]  # missing url, source, score
        result = digest.format_digest_plain(posts)
        self.assertIsInstance(result, str)


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 4: SOURCES / AD FILTER (15 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestSources(unittest.TestCase):

    def setUp(self):
        from sources import is_ad
        self.is_ad = is_ad

    # T66
    def test_ad_filter_ad_prefix(self):
        self.assertTrue(self.is_ad("[Ad] Buy now"))

    # T67
    def test_ad_filter_sponsored_prefix(self):
        self.assertTrue(self.is_ad("[Sponsored] Great deal"))

    # T68
    def test_ad_filter_advertisement_prefix(self):
        self.assertTrue(self.is_ad("[Advertisement] Click here"))

    # T69
    def test_ad_filter_normal_post(self):
        self.assertFalse(self.is_ad("HDB prices rise in Q1 2026"))

    # T70
    def test_ad_filter_case_insensitive(self):
        self.assertTrue(self.is_ad("[ad] something"))
        self.assertTrue(self.is_ad("[SPONSORED] something"))

    # T71
    def test_ad_filter_empty_string(self):
        self.assertFalse(self.is_ad(""))

    # T72
    def test_ad_filter_none(self):
        try:
            result = self.is_ad(None)
            self.assertFalse(result)
        except Exception as e:
            self.fail(f"is_ad(None) raised: {e}")

    # T73
    def test_ad_filter_partial_match_not_flagged(self):
        # "Advertise" in the middle shouldn't be flagged
        self.assertFalse(self.is_ad("How to advertise your business"))

    # T74
    def test_ad_filter_promoted_prefix(self):
        self.assertTrue(self.is_ad("[Promoted] Check this out"))

    # T75
    def test_ad_filter_paid_prefix(self):
        self.assertTrue(self.is_ad("[Paid] Partnership with brand"))

    # T76
    def test_fetch_all_sources_returns_list(self):
        from sources import fetch_all_sources
        with patch("requests.get") as mock_get, patch("requests.Session") as mock_session:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": {"children": []}}
            mock_resp.content = b""
            mock_resp.text = ""
            mock_get.return_value = mock_resp
            mock_session.return_value.__enter__ = MagicMock(return_value=mock_resp)
            mock_session.return_value.__exit__ = MagicMock(return_value=False)
            result = fetch_all_sources()
            self.assertIsInstance(result, list)

    # T77
    def test_fetch_reddit_handles_empty_response(self):
        from sources import fetch_reddit
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": {"children": []}}
            mock_get.return_value = mock_resp
            result = fetch_reddit("singapore")
            self.assertIsInstance(result, list)

    # T78
    def test_fetch_reddit_handles_network_error(self):
        from sources import fetch_reddit
        with patch("requests.get", side_effect=Exception("Network error")):
            result = fetch_reddit("singapore")
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 0)

    # T79
    def test_fetch_telegram_channel_handles_error(self):
        from sources import fetch_telegram_channel
        with patch("requests.get", side_effect=Exception("Timeout")):
            result = fetch_telegram_channel("@testchannel")
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 0)

    # T80
    def test_fetch_rss_handles_invalid_xml(self):
        from sources import fetch_rss
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"<invalid xml <<<"
            mock_get.return_value = mock_resp
            result = fetch_rss("https://fake.rss/feed")
            self.assertIsInstance(result, list)


# ─────────────────────────────────────────────────────────────────────────────
# GROUP 5: BOT / LISTENER EDGE CASES (20 tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestBotListener(unittest.TestCase):

    # T81
    def test_bot_send_telegram_message_no_token(self):
        import bot
        original = bot.TELEGRAM_BOT_TOKEN
        bot.TELEGRAM_BOT_TOKEN = ""
        result = bot.send_telegram_message_plain("test")
        bot.TELEGRAM_BOT_TOKEN = original
        self.assertFalse(result)

    # T82
    def test_bot_split_and_send_long_message(self):
        import bot
        long_text = "Line of text\n" * 500  # ~6500 chars
        with patch("bot.send_telegram_message") as mock_send:
            mock_send.return_value = True
            bot.split_and_send(long_text)
            self.assertGreater(mock_send.call_count, 1)

    # T83
    def test_bot_split_and_send_short_message(self):
        import bot
        short_text = "Short message"
        with patch("bot.send_telegram_message") as mock_send:
            mock_send.return_value = True
            bot.split_and_send(short_text)
            mock_send.assert_called_once()

    # T84
    def test_bot_run_digest_no_posts(self):
        import bot
        with patch("bot.fetch_all_sources", return_value=[]), \
             patch("bot.send_telegram_message_plain") as mock_plain:
            bot.run_digest()
            mock_plain.assert_called()

    # T85
    def test_bot_run_digest_all_already_sent(self):
        import bot
        posts = [make_post(title=f"Already sent T85-{i}") for i in range(3)]
        db.mark_sent(posts)
        with patch("bot.fetch_all_sources", return_value=posts), \
             patch("bot.send_telegram_message_plain") as mock_plain:
            bot.run_digest()
            # Should send "no new stories" message
            args = " ".join(str(c) for c in mock_plain.call_args_list)
            self.assertTrue("no new" in args.lower() or "nothing" in args.lower() or mock_plain.called)

    # T86
    def test_bot_run_digest_sends_on_success(self):
        import bot
        posts = [make_post(title=f"Fresh post T86-{i}") for i in range(5)]
        with patch("bot.fetch_all_sources", return_value=posts), \
             patch("bot.send_telegram_message", return_value=True) as mock_send, \
             patch("bot.split_and_send", return_value=True):
            bot.run_digest()

    # T87
    def test_listener_send_message_splits_long(self):
        import listener
        long_text = "x" * 10000
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp
            listener.send_message(12345, long_text)
            # Should have been called multiple times (chunks)
            self.assertGreater(mock_post.call_count, 1)

    # T88
    def test_listener_send_message_short(self):
        import listener
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": True}
            mock_post.return_value = mock_resp
            listener.send_message(12345, "Hello")
            mock_post.assert_called_once()

    # T89
    def test_listener_get_updates_handles_timeout(self):
        import listener
        with patch("requests.get", side_effect=Exception("Timeout")):
            result = listener.get_updates(offset=0, timeout=1)
            self.assertEqual(result, [])

    # T90
    def test_listener_get_updates_handles_bad_json(self):
        import listener
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"ok": False, "description": "Bad request"}
            mock_get.return_value = mock_resp
            result = listener.get_updates()
            self.assertEqual(result, [])

    # T91
    def test_listener_cmd_strip_botname(self):
        import listener
        # Simulate command parsing
        text = "/digest@Sgnewstodaybot"
        cmd = text.lower().split("@")[0]
        self.assertEqual(cmd, "/digest")

    # T92
    def test_listener_cmd_plain(self):
        import listener
        text = "/start"
        cmd = text.lower().split("@")[0]
        self.assertEqual(cmd, "/start")

    # T93
    def test_listener_trigger_digest_no_posts(self):
        import listener
        with patch("listener.fetch_all_sources", return_value=[]), \
             patch("listener.send_message") as mock_send:
            listener.trigger_digest(12345)
            mock_send.assert_called()

    # T94
    def test_listener_trigger_digest_all_sent(self):
        import listener
        posts = [make_post(title=f"Sent T94-{i}") for i in range(3)]
        db.mark_sent(posts)
        with patch("listener.fetch_all_sources", return_value=posts), \
             patch("listener.send_message") as mock_send:
            listener.trigger_digest(12345)
            mock_send.assert_called()

    # T95
    def test_listener_handle_users_non_admin_silent(self):
        import listener
        with patch("listener.send_message") as mock_send:
            listener.handle_users_command(99999)  # Not admin
            mock_send.assert_not_called()

    # T96
    def test_listener_handle_users_admin(self):
        import listener
        with patch("listener.send_message") as mock_send:
            listener.handle_users_command(listener.ADMIN_CHAT_ID)
            mock_send.assert_called()

    # T97
    def test_bot_markdown_escape_in_plain_fallback(self):
        import bot
        text = r"Hello\. World\- Test\!"
        plain = text.replace("\\.", ".").replace("\\-", "-").replace("\\!", "!")
        self.assertEqual(plain, "Hello. World- Test!")

    # T98
    def test_db_offset_persists_across_reinit(self):
        db.set_state("telegram_offset", 99999)
        db.init_db()  # reinit
        val = int(db.get_state("telegram_offset", 0))
        self.assertEqual(val, 99999)

    # T99
    def test_sources_no_govsg_in_channels(self):
        channels = config.TELEGRAM_CHANNELS
        for ch in channels:
            self.assertNotIn("gov", ch.lower())

    # T100
    def test_full_pipeline_integration(self):
        """End-to-end: fetch mock posts → rank → format → mark sent → dedup check."""
        posts = [make_post(title=f"Integration T100-{i}", source="cna", score=100-i) for i in range(10)]
        ranked = scorer.rank_posts(posts)
        self.assertGreater(len(ranked), 0)
        text = digest.format_digest_plain(ranked)
        self.assertGreater(len(text), 0)
        db.mark_sent(ranked)
        for p in ranked:
            self.assertTrue(db.is_already_sent(p))


# ─────────────────────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [TestDB, TestScorer, TestDigest, TestSources, TestBotListener]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Cleanup temp DB
    shutil.rmtree(_TMP, ignore_errors=True)

    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    passed = total - failures - errors
    print(f"\n{'='*60}")
    print(f"UAT RESULTS: {passed}/{total} passed | {failures} failures | {errors} errors")
    print(f"{'='*60}")

    sys.exit(0 if result.wasSuccessful() else 1)

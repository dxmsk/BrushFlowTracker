"""刷流追新纯规则测试。"""

from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


CORE_PATH = Path(__file__).parents[1] / "plugins.v2" / "brushflowtracker" / "core.py"
SPEC = spec_from_file_location("brushflowtracker_core", CORE_PATH)
core = module_from_spec(SPEC)
SPEC.loader.exec_module(core)


def test_detect_resolution_recognizes_common_aliases():
    assert core.detect_resolution("Film.2160p.UHD.Remux")[0] == "4K"
    assert core.detect_resolution("Film 1080P WEB-DL")[0] == "1080P"
    assert core.detect_resolution("Film 720p HDTV")[1] < core.detect_resolution("Film 4K")[1]


def test_media_key_ignores_release_quality_but_keeps_episode_identity():
    first = core.media_key("Example.Show.S01E02.1080p.WEB-DL.x265")
    upgraded = core.media_key("Example Show S01E02 2160p UHD HDR HEVC")
    next_episode = core.media_key("Example.Show.S01E03.2160p.UHD.HDR")
    assert first == upgraded
    assert first != next_episode


def test_same_episode_hdr_and_sdr_share_identity_and_hdr_wins():
    hdr_title = (
        "The Mystic Nine S01E23 2026 2160p WEB-DL H265 HDR DTS-ADWeb "
        "[The Mystic Nine | Chinese | HDR10 | Official]"
    )
    sdr_title = (
        "The Mystic Nine S01E23 2026 2160p WEB-DL H265 DTS-ADWeb "
        "[The Mystic Nine | Chinese | Official]"
    )
    hdr = core.normalize_item({"title": hdr_title, "enclosure": "https://x/hdr"})
    sdr = core.normalize_item({"title": sdr_title, "enclosure": "https://x/sdr"})

    assert hdr["media_key"] == sdr["media_key"]
    assert hdr["quality_rank"] > sdr["quality_rank"]
    assert core.choose_highest([sdr, hdr]) == [hdr]


def test_chinese_episode_range_distinguishes_season_titles_without_sxxexx():
    episode_5_6_hdr = (
        "Forging Justice S01 2026 2160p WEB-DL H.265 HDR DDP5.1 2Audios-HHWEB "
        "[重器 | 第05-06集 | 4K HDR]"
    )
    episode_5_6_sdr = (
        "Forging Justice S01 2026 2160p WEB-DL H.265 DDP5.1 2Audios-HHWEB "
        "[重器 | 第05-06集 | 4K]"
    )
    episode_7 = "Forging Justice S01 2026 2160p WEB-DL H.265 [重器 | 第07集 | 4K]"

    assert core.media_key(episode_5_6_hdr) == core.media_key(episode_5_6_sdr)
    assert core.media_key(episode_5_6_hdr) != core.media_key(episode_7)


def test_same_quality_prefers_larger_torrent_after_quality_comparison():
    title = "Shrouding the Heavens S01E175 2023 2160p WEB-DL H265 DDP2.0-ADWeb"
    smaller = core.normalize_item({"title": title, "enclosure": "https://x/small", "size": 1 * 1024**3})
    larger = core.normalize_item({"title": title, "enclosure": "https://x/large", "size": 4 * 1024**3})
    lower_resolution = core.normalize_item({
        "title": title.replace("2160p", "1080p"),
        "enclosure": "https://x/1080",
        "size": 20 * 1024**3,
    })

    assert core.choose_highest([smaller, lower_resolution, larger]) == [larger]
    assert core.dedup_allows(larger, {larger["media_key"]: smaller}) is True


def test_screenshot_title_variants_share_global_episode_identity():
    shrouding_titles = [
        "Shrouding the Heaven 2023 S01 E175 2160p WEB-DL H265 AAC 2.0-PTerWEB",
        "Shrouding the Heavens S01E175 2023 2160p WEB-DL H265 DDP2.0-ADWeb",
        "Shrouding.the.Heavens.S01E175.2023.2160p.WEB-DL.H265.AAC-CMCTV",
    ]
    silent_titles = [
        "The Silent Frontline 2026 S01 E15-E16 1080p IQ WEB-DL H264 AAC-PTerWEB",
        "The.Silent.Frontline.S01E15-E16.2026.2160p.IQ.WEB-DL.H265.AAC-CMCTV",
    ]
    forging_titles = [
        "Forging Justice 2026 S01 E05-E06 1080p WEB-DL H264 AAC-PTerWEB",
        "Forging Justice S01 2026 2160p WEB-DL H265 DDP5.1 [重器 第05-06集]",
    ]
    forging_batch = "Forging.Justice.S01E01-E06.2026.1080p.IQ.WEB-DL.H264.AAC-CMCTV"

    assert len({core.media_key(title) for title in shrouding_titles}) == 1
    assert len({core.media_key(title) for title in silent_titles}) == 1
    assert len({core.media_key(title) for title in forging_titles}) == 1
    assert core.media_key(forging_batch) != core.media_key(forging_titles[0])


def test_cross_language_titles_share_identity_from_chinese_description():
    night_watcher = core.normalize_item({
        "title": "[HHC].在下打更人.The.Night.Watcher.S01.2026.2160p.WEB-DL.H.265.HDR.DDP2.0.2Audios-HHWEB",
        "description": "在下打更人 第01-08集 | 4K HDR",
        "size": 7.83 * 1024**3,
    })
    zai_xia = core.normalize_item({
        "title": "Zai Xia Da Geng Ren 2026 S01 E01-E08 1080p WEB-DL H264 DDP2.0-PTerWEB",
        "description": "在下打更人 第1-8集 | 简繁中字",
        "size": 2.17 * 1024**3,
    })
    assert night_watcher["media_key"] == zai_xia["media_key"]
    assert night_watcher["series_alias"] == zai_xia["series_alias"] == "在下打更人"
    assert core.choose_highest([zai_xia, night_watcher]) == [night_watcher]


def test_seed_availability_beats_quality_when_avoiding_dead_seeds():
    title = "Example S01E01 2160p WEB-DL"
    dead = core.normalize_item({"title": title, "seeders": 0, "size": 10 * 1024**3})
    live = core.normalize_item({"title": title, "seeders": 3, "size": 1 * 1024**3})
    assert core.item_downloadability(dead) == 0
    assert core.item_downloadability(live) == 2
    assert core.choose_highest([dead, live]) == [live]


def test_promotion_recognizes_structured_and_text_markers():
    assert core.promotion_of({"downloadvolumefactor": 0, "uploadvolumefactor": 1}) == "free"
    assert core.promotion_of({"title": "[2X FREE] Example"}) == "2xfree"
    assert core.promotion_of({"title": "Freestyle Documentary"}) == "normal"
    assert core.promotion_of({"labels": ["免费"], "title": "Example"}) == "free"


def test_free_until_parses_structured_datetime():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    deadline = core.free_until_of({"freedate": "2026-08-09T12:30:00+00:00"}, now)
    assert deadline == datetime(2026, 8, 9, 12, 30, tzinfo=timezone.utc)


def test_free_until_parses_remaining_duration():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    deadline = core.free_until_of({"description": "免费剩余 1天 2小时 30分钟"}, now)
    assert deadline == now + timedelta(days=1, hours=2, minutes=30)


def test_free_remaining_time_also_marks_item_free_without_free_title_marker():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    item = core.normalize_item(
        {
            "title": "[综艺] Heart Signal S09E01 Special 2160p WEB-DL",
            "description": "免费剩余时间：23时26分",
            "enclosure": "https://audiences.me/download.php?id=704378",
        },
        now,
    )
    assert item["promotion"] == "free"
    assert item["free_until"] == now + timedelta(hours=23, minutes=26)


def test_match_rule_requires_all_whitelist_keywords_and_reports_missing_term():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    item = core.normalize_item({"title": "Example 4K HDR", "enclosure": "https://x/t", "size": 20 * 1024**3}, now)
    matched, _ = core.match_rule(item, {"whitelist_keywords": ["example", "HDR"]}, now)
    rejected, reason = core.match_rule(item, {"whitelist_keywords": ["example", "DV"]}, now)
    assert matched is True
    assert rejected is False
    assert reason == "缺少白名单关键词：DV"


def test_match_rule_blacklist_takes_precedence_and_reports_matching_terms():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    item = core.normalize_item({
        "title": "Example 4K HDR BAD-GROUP",
        "enclosure": "https://x/t",
    }, now)
    matched, reason = core.match_rule(item, {
        "whitelist_keywords": ["Example", "HDR"],
        "blacklist_keywords": ["CAM", "BAD-GROUP"],
    }, now)
    assert matched is False
    assert reason == "命中黑名单关键词：BAD-GROUP"


def test_match_rule_applies_exclusions_resolution_age_and_size():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    item = core.normalize_item(
        {
            "title": "Example 1080p WEB-DL",
            "description": "bad-group",
            "enclosure": "https://x/t",
            "size": 4 * 1024**3,
            "pubdate": now - timedelta(minutes=15),
        },
        now,
    )
    assert core.match_rule(item, {"excluded_keywords": ["BAD-GROUP"]}, now)[0] is False
    assert core.match_rule(item, {"resolutions": ["4K"]}, now)[0] is False
    assert core.match_rule(item, {"publish_age_from_minutes": 0, "publish_age_to_minutes": 10}, now)[0] is False
    assert core.match_rule(item, {"size_from_gib": 5, "size_to_gib": 30}, now)[0] is False


def test_match_rule_rejects_missing_pubdate_when_age_limit_is_enabled():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    item = core.normalize_item({"title": "Example", "enclosure": "https://x/t"}, now)
    assert core.match_rule(item, {"publish_age_from_minutes": 0, "publish_age_to_minutes": 60}, now) == (
        False,
        "缺少发种时间，无法判断范围",
    )


def test_match_rule_accepts_configured_age_and_size_ranges():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    item = core.normalize_item(
        {
            "title": "Example 4K",
            "enclosure": "https://x/t",
            "size": 20 * 1024**3,
            "pubdate": now - timedelta(minutes=15),
        },
        now,
    )
    rule = {
        "publish_age_from_minutes": 0,
        "publish_age_to_minutes": 30,
        "size_from_gib": 0,
        "size_to_gib": 30,
    }
    assert core.match_rule(item, rule, now) == (True, "命中")


def test_match_rule_supports_mixed_time_and_size_units():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    item = core.normalize_item({
        "title": "Example 4K",
        "enclosure": "https://x/t",
        "size": 1536 * 1024**2,
        "pubdate": now - timedelta(hours=2),
    }, now)
    rule = {
        "publish_age_from_value": 90,
        "publish_age_from_unit": "minutes",
        "publish_age_to_value": 3,
        "publish_age_to_unit": "hours",
        "size_from_value": 1000,
        "size_from_unit": "mib",
        "size_to_value": 2,
        "size_to_unit": "gib",
    }
    assert core.match_rule(item, rule, now) == (True, "命中")
    assert core.match_rule(item, {**rule, "publish_age_to_value": 7199, "publish_age_to_unit": "seconds"}, now)[0] is False
    assert core.match_rule(item, {**rule, "size_to_value": 1500, "size_to_unit": "mib"}, now)[0] is False


def test_match_rule_applies_free_filter():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    free = core.normalize_item({"title": "[FREE] Example", "enclosure": "https://x/t"}, now)
    normal = core.normalize_item({"title": "Example", "enclosure": "https://x/n"}, now)
    assert core.match_rule(free, {"promotion": "free_or_2xfree"}, now)[0] is True
    assert core.match_rule(normal, {"promotion": "free_or_2xfree"}, now)[0] is False


def test_choose_highest_keeps_one_item_per_media_in_stable_order():
    items = [
        {"title": "A 1080p", "media_key": "a", "resolution_rank": 4},
        {"title": "B 720p", "media_key": "b", "resolution_rank": 2},
        {"title": "A 4K", "media_key": "a", "resolution_rank": 5},
    ]
    chosen = core.choose_highest(items)
    assert [item["title"] for item in chosen] == ["A 4K", "B 720p"]


def test_persistent_dedup_only_allows_strict_upgrade():
    records = {"a": {"resolution_rank": 4}}
    assert core.dedup_allows({"media_key": "a", "resolution_rank": 4}, records) is False
    assert core.dedup_allows({"media_key": "a", "resolution_rank": 5}, records) is True
    assert core.dedup_allows({"media_key": "b", "resolution_rank": 2}, records) is True


def test_cleanup_returns_first_matching_rule_in_order():
    torrent = {"tags": "追新动画,anime", "ratio": 2.5, "seeding_time": 10 * 3600}
    rules = [
        {"id": "too-early", "enabled": True, "labels": ["anime"], "min_seed_hours": 20, "min_ratio": 1},
        {"id": "first-match", "enabled": True, "labels": ["anime"], "min_seed_hours": 5, "min_ratio": 2},
        {"id": "later-match", "enabled": True, "labels": [], "min_seed_hours": 0, "min_ratio": 0},
    ]
    matched = core.first_cleanup_rule(torrent, rules)
    assert matched["id"] == "first-match"


def test_cleanup_requires_configured_task_label():
    torrent = {"tags": "其他任务", "ratio": 99, "seeding_time": 999999}
    rules = [{"enabled": True, "labels": ["追新动画"], "min_seed_hours": 0, "min_ratio": 0}]
    assert core.first_cleanup_rule(torrent, rules) is None


def test_cleanup_matches_any_selected_task_label():
    torrent = {"tags": "任务 B", "ratio": 2, "seeding_time": 5 * 3600}
    rules = [{"id": "match", "enabled": True, "labels": ["任务 A", "任务 B"], "min_seed_hours": 1, "min_ratio": 1}]
    assert core.first_cleanup_rule(torrent, rules)["id"] == "match"


def test_normalize_item_reads_common_rss_publish_time_fields():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    item = core.normalize_item(
        {"title": "Example", "enclosure": "https://x/t", "published_at": now - timedelta(minutes=12)},
        now,
    )
    assert item["pubdate"] == now - timedelta(minutes=12)
    assert core.match_rule(item, {"publish_age_from_minutes": 0, "publish_age_to_minutes": 30}, now)[0] is True


def test_promotion_known_distinguishes_missing_from_explicit_normal_factor():
    unknown = core.normalize_item({"title": "Example", "enclosure": "https://x/u"})
    normal = core.normalize_item({"title": "Example", "enclosure": "https://x/n", "downloadfactor": 1})
    assert unknown["promotion_known"] is False
    assert normal["promotion_known"] is True

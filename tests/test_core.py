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


def test_promotion_recognizes_structured_and_text_markers():
    assert core.promotion_of({"downloadvolumefactor": 0, "uploadvolumefactor": 1}) == "free"
    assert core.promotion_of({"title": "[2X FREE] Example"}) == "2xfree"
    assert core.promotion_of({"title": "Freestyle Documentary"}) == "normal"


def test_free_until_parses_structured_datetime():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    deadline = core.free_until_of({"freedate": "2026-08-09T12:30:00+00:00"}, now)
    assert deadline == datetime(2026, 8, 9, 12, 30, tzinfo=timezone.utc)


def test_free_until_parses_remaining_duration():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    deadline = core.free_until_of({"description": "免费剩余 1天 2小时 30分钟"}, now)
    assert deadline == now + timedelta(days=1, hours=2, minutes=30)


def test_match_rule_requires_all_required_keywords():
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    item = core.normalize_item({"title": "Example 4K HDR", "enclosure": "https://x/t", "size": 20 * 1024**3}, now)
    matched, _ = core.match_rule(item, {"required_keywords": ["example", "HDR"]}, now)
    rejected, reason = core.match_rule(item, {"required_keywords": ["example", "DV"]}, now)
    assert matched is True
    assert rejected is False
    assert reason == "缺少必须关键词"


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

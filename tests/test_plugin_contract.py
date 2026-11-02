"""使用最小宿主替身验证 MoviePilot 插件入口契约。"""

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest


class Response:
    """测试使用的 MoviePilot 标准响应替身。"""

    def __init__(self, success, message=None, data=None):
        self.success = success
        self.message = message
        self.data = data if data is not None else {}


class PluginBase:
    """仅实现本插件初始化所需持久化方法的宿主替身。"""

    def __init__(self):
        self._test_data = {}
        self._test_config = {}

    def get_data(self, key):
        return self._test_data.get(key)

    def save_data(self, key, value):
        self._test_data[key] = value

    def update_config(self, value):
        self._test_config = value


class SilentLogger:
    """吞掉插件测试日志的最小日志替身。"""

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class FakeDownloader:
    """记录添加参数的 qBittorrent 服务替身。"""

    def __init__(self):
        self.added = []

    def add_torrent(self, **kwargs):
        self.added.append(kwargs)
        return True, ["ABC123"]


@pytest.fixture
def plugin_module(monkeypatch):
    """注入最小 MoviePilot 模块并加载插件包。"""
    app = ModuleType("app")
    schemas = ModuleType("app.schemas")
    schemas.Response = Response
    app.schemas = schemas

    downloader = ModuleType("app.helper.downloader")
    downloader.DownloaderHelper = type(
        "DownloaderHelper",
        (),
        {"get_service": lambda *_args, **_kwargs: None, "get_services": lambda *_args, **_kwargs: {}},
    )
    rss = ModuleType("app.helper.rss")
    rss.RssHelper = type("RssHelper", (), {})
    thread = ModuleType("app.helper.thread")
    thread.ThreadHelper = type("ThreadHelper", (), {"submit": lambda *_args, **_kwargs: None})
    log = ModuleType("app.log")
    log.logger = SilentLogger()
    plugins = ModuleType("app.plugins")
    plugins._PluginBase = PluginBase
    scheduler = ModuleType("app.scheduler")
    scheduler.Scheduler = type("Scheduler", (), {"update_plugin_job": lambda *_args: None})

    modules = {
        "app": app,
        "app.schemas": schemas,
        "app.helper": ModuleType("app.helper"),
        "app.helper.downloader": downloader,
        "app.helper.rss": rss,
        "app.helper.thread": thread,
        "app.log": log,
        "app.plugins": plugins,
        "app.scheduler": scheduler,
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    package_root = Path(__file__).parents[1] / "plugins.v2"
    monkeypatch.syspath_prepend(str(package_root))
    sys.modules.pop("brushflowtracker", None)
    loaded = import_module("brushflowtracker")
    yield loaded
    for name in list(sys.modules):
        if name == "brushflowtracker" or name.startswith("brushflowtracker."):
            sys.modules.pop(name, None)


def test_default_plugin_contract(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    assert plugin.get_state() is False
    assert plugin.get_service() == []
    assert plugin.get_render_mode() == ("vue", "dist/assets")
    assert {route["path"] for route in plugin.get_api()} == {
        "/status", "/tasks", "/settings", "/run", "/test-downloader"
    }


def test_enabled_plugin_registers_three_independent_intervals(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin(
        {
            "enabled": True,
            "rss_interval_minutes": 11,
            "free_monitor_interval_minutes": 3,
            "cleanup_interval_minutes": 31,
        }
    )
    services = plugin.get_service()
    assert [service["id"] for service in services] == ["RssRefresh", "FreeMonitor", "Cleanup"]
    assert [service["kwargs"]["minutes"] for service in services] == [11, 3, 31]


def test_config_normalization_assigns_unique_site_and_rule_ids(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin(
        {
            "sites": [
                {
                    "name": "A",
                    "rss_rules": [{"name": "R1"}, {"name": "R2"}],
                    "cleanup_rules": [{"name": "D1"}],
                },
                {"name": "B"},
            ]
        }
    )
    ids = [site["id"] for site in plugin._sites]
    rule_ids = [
        rule["id"]
        for site in plugin._sites
        for key in ("rss_rules", "cleanup_rules")
        for rule in site[key]
    ]
    assert len(ids) == len(set(ids)) == 2
    assert len(rule_ids) == len(set(rule_ids)) == 3
    assert plugin._sites[0]["cleanup_rules"][0]["labels"] == ["R1", "R2"]


def test_legacy_limits_migrate_to_ranges(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin(
        {
            "sites": [
                {
                    "name": "A",
                    "rss_rules": [{"name": "R1", "max_age_minutes": 30, "min_size_gib": 5}],
                }
            ]
        }
    )
    task = plugin._sites[0]["rss_rules"][0]
    assert task["publish_age_from_value"] == 0
    assert task["publish_age_from_unit"] == "minutes"
    assert task["publish_age_to_value"] == 30
    assert task["publish_age_to_unit"] == "minutes"
    assert task["size_from_value"] == 5
    assert task["size_from_unit"] == "gib"
    assert task["size_to_value"] is None
    assert task["size_to_unit"] == "gib"
    assert "max_age_minutes" not in task
    assert "min_size_gib" not in task


def test_status_exposes_one_shared_downloader_setting(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({"downloader": "main-qb", "sites": [{"name": "A"}, {"name": "B"}]})
    response = plugin.get_status()
    assert response.success is True
    assert response.data["settings"]["downloader"] == "main-qb"
    assert len(response.data["sites"]) == 2


def test_task_name_is_the_only_qbittorrent_tag(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    downloader = FakeDownloader()
    service = type("SimpleService", (), {"instance": downloader})()
    site = {"id": "site-a", "name": "站点 A"}
    rule = {"id": "rule-a", "name": "动漫追新"}
    item = {
        "title": "Example S01E01 1080P",
        "enclosure": "https://tracker.example/download/1",
        "resolution": "1080P",
        "promotion": "normal",
        "free_until": None,
    }
    assert plugin._add_item(site, rule, item, service) is True
    assert downloader.added[0]["tag"] == "动漫追新"
    assert plugin._state["managed"]["abc123"]["tags"] == ["动漫追新"]


def test_selection_log_contains_task_title_link_and_reason(plugin_module, monkeypatch):
    messages = []
    recorder = type("Recorder", (), {"info": lambda _self, message: messages.append(message)})()
    monkeypatch.setattr(plugin_module, "logger", recorder)
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    plugin._log_selection(
        {"id": "a", "name": "站点 A"},
        {"id": "r", "name": "4K 追新", "blacklist_keywords": ["CAM"]},
        {"title": "Example 2160P CAM", "enclosure": "https://tracker.example/download/2"},
        "排除",
        "命中黑名单关键词：CAM",
    )
    assert "任务=4K 追新" in messages[0]
    assert "名称=Example 2160P CAM" in messages[0]
    assert "链接=https://tracker.example/download/2" in messages[0]
    assert "原因=命中黑名单关键词：CAM" in messages[0]
    assert plugin._state["history"][0]["event"] == "selection"
    assert plugin._state["history"][0]["outcome"] == "排除"
    assert "黑名单(任一排除)=CAM" in plugin._state["history"][0]["rule_summary"]
    assert "黑名单命中=CAM" in plugin._state["history"][0]["actual_summary"]


def test_download_selection_enriches_existing_added_history_without_duplicate(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    plugin._state["history"] = [{
        "event": "added", "title": "Example 4K", "time": "2026-08-13T10:00:00+08:00",
    }]
    plugin._log_selection(
        {"id": "a", "name": "站点 A"},
        {"id": "r", "name": "4K 追新", "whitelist_keywords": ["Example"]},
        {"title": "Example 4K", "enclosure": "https://tracker.example/download/4", "resolution": "4K"},
        "添加",
        "符合全部条件",
    )
    assert len(plugin._state["history"]) == 1
    assert plugin._state["history"][0]["event"] == "added"
    assert plugin._state["history"][0]["outcome"] == "添加"
    assert "白名单命中=Example" in plugin._state["history"][0]["actual_summary"]


def test_audiences_detail_url_can_be_recovered_from_download_link(plugin_module):
    tracker = plugin_module.BrushFlowTracker
    assert tracker._detail_url({"link": "https://audiences.me/details.php?id=704450&hit=1"}) == (
        "https://audiences.me/details.php?id=704450&hit=1"
    )


def test_site_uid_and_passkey_are_added_without_overwriting_existing_values(plugin_module):
    tracker = plugin_module.BrushFlowTracker
    url = tracker._rss_url(
        "https://tracker.example/torrentrss.php?rows=20",
        {"uid": "123", "passkey": "secret"},
    )
    assert "uid=123" in url
    assert "passkey=secret" in url
    existing = tracker._rss_url(
        "https://tracker.example/torrentrss.php?uid=999&passkey=old",
        {"uid": "123", "passkey": "secret"},
    )
    assert "uid=999" in existing and "uid=123" not in existing
    assert "passkey=old" in existing and "passkey=secret" not in existing


def test_task_rss_key_supports_default_custom_name_and_placeholder(plugin_module):
    tracker = plugin_module.BrushFlowTracker
    default_url = tracker._rss_url(
        "https://tracker.example/rss.php?rows=20",
        {"rss_key": "rss-secret", "rss_key_name": "rsskey"},
    )
    assert "rsskey=rss-secret" in default_url
    custom_url = tracker._rss_url(
        "https://tracker.example/rss.php?key={RSSKEY}",
        {"rss_key": "custom-secret", "rss_key_name": "authkey"},
    )
    assert "key=custom-secret" in custom_url
    assert "authkey=custom-secret" not in custom_url
    assert tracker._detail_url({"enclosure": "https://audiences.me/download.php?id=704450&downhash=secret"}) == (
        "https://audiences.me/details.php?id=704450&hit=1"
    )


def test_audiences_detail_lookup_reuses_moviepilot_cookie(plugin_module, monkeypatch):
    captured = {}
    db = ModuleType("app.db")
    utils = ModuleType("app.utils")
    site_oper = ModuleType("app.db.site_oper")
    http = ModuleType("app.utils.http")

    class FakeSiteOper:
        def get_by_domain(self, domain):
            captured["domain"] = domain
            return type("Site", (), {"cookie": "uid=1; pass=secret", "ua": "MoviePilot-UA", "proxy": 0})()

    class FakeRequestUtils:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def get_res(self, url):
            captured["url"] = url
            return type("Response", (), {"status_code": 200, "text": "<h1>[免费] 剩余时间：23时53分</h1>"})()

    site_oper.SiteOper = FakeSiteOper
    http.RequestUtils = FakeRequestUtils
    monkeypatch.setitem(sys.modules, "app.db", db)
    monkeypatch.setitem(sys.modules, "app.utils", utils)
    monkeypatch.setitem(sys.modules, "app.db.site_oper", site_oper)
    monkeypatch.setitem(sys.modules, "app.utils.http", http)

    plugin = plugin_module.BrushFlowTracker()
    plugin._request_timeout_seconds = 20
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    result = plugin._fetch_detail_promotion(
        {"use_proxy": False},
        {"title": "Call Me By Fire 2160p", "enclosure": "https://audiences.me/download.php?id=704450"},
        now,
    )

    assert result["promotion"] == "free"
    assert result["free_until"] == now + timedelta(hours=23, minutes=53)
    assert captured["domain"] == "audiences.me"
    assert captured["cookies"] == "uid=1; pass=secret"
    assert captured["url"] == "https://audiences.me/details.php?id=704450&hit=1"


def test_flush_keeps_one_highest_resolution_across_all_sites(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    downloader = FakeDownloader()
    service = type("SimpleService", (), {"instance": downloader})()
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    site_a = {"id": "a", "name": "站点 A"}
    site_b = {"id": "b", "name": "站点 B"}
    rule_a = {"id": "ra", "name": "任务 A"}
    rule_b = {"id": "rb", "name": "任务 B"}

    def candidate(site, rule, url, resolution):
        item = plugin_module.normalize_item(
            {"title": f"Call Me By Fire S06E01 {resolution} WEB-DL", "enclosure": url}, now
        )
        return {"site": site, "rule": rule, "item": item, "url_key": url, "now": now}

    plugin._pending_candidates = [
        candidate(site_a, rule_a, "https://a.example/1080", "1080P"),
        candidate(site_b, rule_b, "https://b.example/2160", "2160P"),
        candidate(site_a, rule_a, "https://a.example/2160", "2160P"),
    ]
    result = plugin._flush_pending_candidates(service)

    assert result["added"] == 1
    assert result["site_dedup"] == 2
    assert [row["content"] for row in downloader.added] == ["https://b.example/2160"]


def test_flush_keeps_hdr_when_same_site_episode_has_two_4k_releases(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    downloader = FakeDownloader()
    service = type("SimpleService", (), {"instance": downloader})()
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    site = {"id": "a", "name": "Site A"}
    rule = {"id": "ra", "name": "Task A"}

    def candidate(title, url):
        return {
            "site": site,
            "rule": rule,
            "item": plugin_module.normalize_item({"title": title, "enclosure": url}, now),
            "url_key": url,
            "now": now,
        }

    base = "The Mystic Nine S01E23 2026 2160p WEB-DL H265 DTS-ADWeb"
    plugin._pending_candidates = [
        candidate(f"{base} [Chinese | Official]", "https://a.example/sdr"),
        candidate(f"{base} HDR [Chinese | HDR10 | Official]", "https://a.example/hdr"),
    ]
    result = plugin._flush_pending_candidates(service)

    assert result["added"] == 1
    assert result["site_dedup"] == 1
    assert [row["content"] for row in downloader.added] == ["https://a.example/hdr"]


def test_adding_upgrade_pauses_old_until_new_copy_is_complete(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    now = datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc)
    low = plugin_module.normalize_item({
        "title": "Shrouding the Heavens S01E175 2023 1080p WEB-DL H265",
        "enclosure": "https://a.example/1080",
        "size": 1 * 1024**3,
    }, now)
    high = plugin_module.normalize_item({
        "title": "Shrouding the Heavens S01E175 2023 2160p WEB-DL H265",
        "enclosure": "https://a.example/2160",
        "size": 4 * 1024**3,
    }, now)
    plugin._state["managed"]["low"] = {
        "site_id": "other-site", "title": low["title"], "size": low["size"], "added_at": now.isoformat()
    }

    class ReplacementDownloader:
        def __init__(self):
            self.deleted = []
            self.paused = []
            self.rows = [{"hash": "LOW", "name": low["title"], "size": low["size"],
                          "progress": 0.5, "amount_left": 100, "state": "downloading"}]

        def get_torrents(self):
            return self.rows, False

        def add_torrent(self, **_kwargs):
            self.rows.append({"hash": "HIGH", "name": high["title"], "size": high["size"],
                              "progress": 0.1, "amount_left": 100, "state": "downloading"})
            return True, ["HIGH"]

        def pause_torrents(self, ids):
            self.paused.extend(ids)
            return True

        def delete_torrents(self, ids, delete_file=False):
            self.deleted.append((ids, delete_file))
            return True

    downloader = ReplacementDownloader()
    service = type("SimpleService", (), {"instance": downloader})()
    result = plugin._add_item(
        {"id": "a", "name": "Site A"},
        {"id": "r", "name": "Task A"},
        high,
        service,
    )

    assert result is True
    assert downloader.deleted == []
    assert downloader.paused == ["low"]
    assert set(plugin._state["managed"]) == {"low", "high"}
    assert plugin._state["managed"]["low"]["paused_by_plugin"] is True
    assert plugin._state["managed"]["high"]["replacement_for"] == ["low"]
    assert plugin._finalize_replacements(service, downloader.rows) == 0
    assert downloader.deleted == []

    downloader.rows[1].update(progress=1, amount_left=0, state="uploading")
    assert plugin._finalize_replacements(service, downloader.rows) == 1
    assert downloader.deleted == [(["low"], True)]
    assert set(plugin._state["managed"]) == {"high"}
    assert not plugin._state["managed"]["high"].get("replacement_for")
    assert plugin._finalize_replacements(service, downloader.rows) == 0
    assert downloader.deleted == [(["low"], True)]


def test_adding_upgrade_keeps_completed_inferior_task_and_files(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    now = datetime.now(timezone.utc)
    low = plugin_module.normalize_item({
        "title": "Example S01E01 1080p WEB-DL", "enclosure": "https://a.example/low",
    }, now)
    high = plugin_module.normalize_item({
        "title": "Example S01E01 2160p WEB-DL", "enclosure": "https://a.example/high",
    }, now)
    plugin._state["managed"]["low"] = {"site_id": "a", "title": low["title"]}

    class CompletedDownloader:
        def __init__(self):
            self.deleted = []

        def get_torrents(self):
            return [{
                "hash": "LOW", "name": low["title"], "progress": 1.0, "amount_left": 0,
                "size": 1000, "state": "uploading",
            }], False

        def add_torrent(self, **_kwargs):
            return True, ["HIGH"]

        def delete_torrents(self, ids, delete_file=False):
            self.deleted.append((ids, delete_file))
            return True

    downloader = CompletedDownloader()
    service = type("SimpleService", (), {"instance": downloader})()

    assert plugin._add_item({"id": "a", "name": "A"}, {"id": "r", "name": "追新"}, high, service)
    assert downloader.deleted == []
    assert set(plugin._state["managed"]) == {"low", "high"}


def test_delayed_qb_hash_does_not_mistake_old_same_tag_task_for_new_upgrade(
    plugin_module, monkeypatch
):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    now = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    standard = plugin_module.normalize_item({
        "title": "Mystic.Nine.S01.2026.2160p.YK.WEB-DL.H265.HFR.HQ.DTS5.1-HHWEB",
        "enclosure": "https://tracker.example/standard",
        "size": 30 * 1024**3,
    }, now)
    dolby_vision = plugin_module.normalize_item({
        "title": "Mystic.Nine.S01.2026.2160p.YK.WEB-DL.H265.DV.HFR.HQ.DTS5.1-HHWEB",
        "enclosure": "https://tracker.example/dv",
        "size": 31 * 1024**3,
    }, now)
    assert standard["media_key"] == dolby_vision["media_key"]
    assert dolby_vision["quality_rank"] > standard["quality_rank"]
    plugin._state["managed"]["old"] = {
        **plugin._identity_fields(standard), "identity_uncertain": False,
        "site_id": "a", "site_name": "Site A", "rule_id": "r", "rule_name": "Task A",
        "title": standard["title"], "size": standard["size"], "added_at": now.isoformat(),
    }

    class DelayedHashDownloader:
        def __init__(self):
            self.new_visible = False
            self.deleted = []
            self.paused = []

        def get_torrents(self):
            rows = [{
                "hash": "OLD", "name": standard["title"], "tags": "Task A", "added_on": 1,
                "size": standard["size"], "progress": 0.2, "amount_left": 100,
                "state": "pausedDL" if self.paused else "downloading",
            }]
            if self.new_visible:
                rows.append({
                    "hash": "NEW", "name": dolby_vision["title"], "tags": "Task A", "added_on": 2,
                    "size": dolby_vision["size"], "progress": 0.1, "amount_left": 200, "state": "downloading",
                })
            return rows, False

        def pause_torrents(self, ids):
            self.paused.extend(ids)
            return True

        def add_torrent(self, **_kwargs):
            return True, []

        def delete_torrents(self, ids, delete_file=False):
            self.deleted.append((ids, delete_file))
            return True

    monkeypatch.setattr(plugin_module.time, "sleep", lambda _seconds: None)
    downloader = DelayedHashDownloader()
    service = type("SimpleService", (), {"instance": downloader})()

    assert plugin._add_item(
        {"id": "a", "name": "Site A"},
        {"id": "r", "name": "Task A"},
        dolby_vision,
        service,
    ) is True
    assert "old" in plugin._state["managed"]
    assert len(plugin._state["pending_managed"]) == 1
    assert plugin._state["pending_managed"][0]["existing_hashes"] == ["old"]
    assert plugin._state["pending_managed"][0]["replace_hashes"] == ["old"]
    assert downloader.deleted == []
    assert downloader.paused == [], "Unconfirmed upgrades must leave the old download running"

    downloader.new_visible = True
    torrents, _failed = downloader.get_torrents()
    plugin._reconcile_pending_managed(service, torrents)

    assert plugin._state["pending_managed"] == []
    assert set(plugin._state["managed"]) == {"old", "new"}
    assert plugin._state["managed"]["new"]["replacement_for"] == ["old"]
    assert downloader.paused == ["old"]
    assert downloader.deleted == []
    assert {row["hash"] for row in torrents} == {"OLD", "NEW"}
    assert plugin._finalize_replacements(service, torrents) == 0

    torrents[1].update(progress=1, amount_left=0, state="uploading")
    assert plugin._finalize_replacements(service, torrents) == 1
    assert set(plugin._state["managed"]) == {"new"}
    assert downloader.deleted == [(["old"], True)]


def test_delayed_upgrade_retries_inferior_task_deletion(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    plugin._state["managed"]["old"] = {"site_id": "a", "title": "Show S01E01 2160p"}
    plugin._state["pending_managed"] = [{
        "site_id": "a", "rule_name": "Task A", "title": "Show S01E01 2160p DV",
        "existing_hashes": ["old"], "replace_hashes": ["old"],
    }]

    class RetryDownloader:
        def __init__(self):
            self.attempts = 0
            self.paused = []

        def pause_torrents(self, ids):
            self.paused.extend(ids)
            return True

        def delete_torrents(self, ids, delete_file=False):
            assert ids == ["old"] and delete_file is True
            self.attempts += 1
            return self.attempts > 1

    downloader = RetryDownloader()
    service = type("SimpleService", (), {"instance": downloader})()
    torrents = [
        {"hash": "OLD", "name": "Show S01E01 2160p", "tags": "Task A", "size": 1000,
         "progress": 0.5, "amount_left": 500, "state": "downloading"},
        {"hash": "NEW", "name": "Show S01E01 2160p DV", "tags": "Task A", "size": 1000,
         "progress": 0.1, "amount_left": 900, "state": "downloading"},
    ]

    plugin._reconcile_pending_managed(service, torrents)
    assert plugin._state["pending_managed"] == []
    assert set(plugin._state["managed"]) == {"old", "new"}
    assert downloader.paused == ["old"]
    assert downloader.attempts == 0
    assert plugin._finalize_replacements(service, torrents) == 0
    assert downloader.attempts == 0

    torrents[1].update(progress=1, amount_left=0, state="uploading")
    assert plugin._finalize_replacements(service, torrents) == 0
    assert downloader.attempts == 1
    assert set(plugin._state["managed"]) == {"old", "new"}
    assert plugin._state["managed"]["new"]["replacement_for"] == ["old"]

    assert plugin._finalize_replacements(service, torrents) == 1
    assert downloader.attempts == 2
    assert set(plugin._state["managed"]) == {"new"}
    assert not plugin._state["managed"]["new"].get("replacement_for")


def test_existing_duplicates_keep_best_quality_then_largest_size(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    base = "Forging Justice S01 2026 2160p WEB-DL H.265 DDP5.1 [重器 | 第05-06集]"
    torrents = [
        {"hash": "sdr", "name": base, "size": 10 * 1024**3, "progress": 0.8},
        {"hash": "hdr-small", "name": f"{base} HDR", "size": 3 * 1024**3, "progress": 0.9},
        {"hash": "hdr-large", "name": f"{base} HDR", "size": 6 * 1024**3, "progress": 0.5},
    ]
    for index, torrent in enumerate(torrents):
        plugin._state["managed"][torrent["hash"]] = {
            "site_id": "a" if index < 2 else "b",
            "site_name": "Site A" if index < 2 else "Site B",
            "title": torrent["name"],
        }

    class ExistingDownloader:
        def __init__(self):
            self.deleted = []
            self.paused = []

        def get_torrents(self):
            return torrents, False

        def pause_torrents(self, ids):
            self.paused.extend(ids)
            return True

        def delete_torrents(self, ids, delete_file=False):
            self.deleted.extend(ids)
            assert delete_file is True
            return True

    downloader = ExistingDownloader()
    service = type("SimpleService", (), {"instance": downloader})()

    assert plugin._deduplicate_managed_torrents(service, "a") == 0
    assert downloader.deleted == []
    assert set(downloader.paused) == {"sdr", "hdr-small"}
    assert set(plugin._state["managed"]) == {"sdr", "hdr-small", "hdr-large"}
    assert set(plugin._state["managed"]["hdr-large"]["replacement_for"]) == {"sdr", "hdr-small"}
    assert torrents[2].get("state") != "pausedDL"

    torrents[2].update(progress=1, amount_left=0, state="uploading")
    assert plugin._deduplicate_managed_torrents(service, "a") == 2
    assert set(downloader.deleted) == {"sdr", "hdr-small"}
    assert set(plugin._state["managed"]) == {"hdr-large"}


def test_existing_dedup_never_deletes_completed_duplicate(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    low_title = "Example S01E01 1080p WEB-DL"
    high_title = "Example S01E01 2160p WEB-DL"
    plugin._state["managed"] = {
        "low": {"site_id": "a", "title": low_title},
        "high": {"site_id": "a", "title": high_title},
    }

    class ExistingDownloader:
        def __init__(self):
            self.deleted = []

        def get_torrents(self):
            return [
                {"hash": "LOW", "name": low_title, "progress": 1, "amount_left": 0, "size": 1000},
                {"hash": "HIGH", "name": high_title, "progress": 0.5, "amount_left": 100, "size": 2000},
            ], False

        def delete_torrents(self, ids, delete_file=False):
            self.deleted.append((ids, delete_file))
            return True

    downloader = ExistingDownloader()
    service = type("Service", (), {"instance": downloader})()

    assert plugin._deduplicate_managed_torrents(service) == 0
    assert downloader.deleted == []
    assert set(plugin._state["managed"]) == {"low", "high"}


def test_lightweight_status_does_not_connect_to_qb(plugin_module, monkeypatch):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({"sites": [{"id": "a", "name": "A"}]})
    monkeypatch.setattr(
        plugin, "_qb_service", lambda *_args, **_kwargs: pytest.fail("lightweight status connected to qB")
    )

    response = plugin.get_status("a", include_tasks=False, include_downloaders=False)

    assert response.success is True
    assert response.data["tasks"] == []
    assert response.data["downloaders"] == []


def test_dead_seed_monitor_retains_last_copy_and_releases_dedup(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({"dead_seed_wait_minutes": 30, "dead_seed_min_seeders": 1, "dead_seed_delete_files": True})
    now = datetime.now(timezone.utc)
    title = "Example S01E01 2160p WEB-DL H265"
    item = plugin_module.normalize_item({"title": title, "enclosure": "https://a.example/dead"}, now)
    plugin._state["managed"]["dead"] = {
        "site_id": "a", "title": title, "link": item["enclosure"], "added_at": now.isoformat()
    }
    plugin._state["dedup_records"][item["media_key"]] = {
        "title": title, "resolution_rank": item["resolution_rank"], "quality_rank": item["quality_rank"]
    }
    plugin._state["dead_seed_watch"]["dead"] = {
        "since": (now - timedelta(minutes=31)).isoformat(), "progress": 0
    }

    class DeadTasks:
        def __init__(self):
            self.deleted = []
            self.paused = []

        def pause_torrents(self, ids):
            self.paused.extend(ids)
            return True

        def delete_torrents(self, ids, delete_file=False):
            self.deleted.append((ids, delete_file))
            return True

    adapter = DeadTasks()
    service = type("Service", (), {"instance": adapter})()
    torrents = [{
        "hash": "dead", "name": title, "progress": 0.1, "amount_left": 100,
        "dlspeed": 0, "num_seeds": 0, "num_complete": 0,
    }]
    # Progress since the previous observation restarts the stall window.
    assert plugin._monitor_dead_seeds(service, torrents, "a") == 0
    assert adapter.deleted == [] and adapter.paused == []
    assert plugin._state["dead_seed_watch"]["dead"]["progress"] == 0.1
    plugin._state["dead_seed_watch"]["dead"]["since"] = (now - timedelta(minutes=31)).isoformat()

    assert plugin._monitor_dead_seeds(service, torrents, "a") == 0
    assert adapter.deleted == []
    assert adapter.paused == ["dead"]
    assert "dead" in plugin._state["managed"]
    assert plugin._state["managed"]["dead"]["recovery_state"] == "stalled"
    assert plugin._state["managed"]["dead"]["paused_by_plugin"] is True
    assert item["media_key"] not in plugin._state["dedup_records"]
    assert plugin._site_dedup_allows("a", item)


def test_dead_seed_uses_persisted_fallback_after_publish_window_expires(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({"dead_seed_wait_minutes": 30, "dead_seed_min_seeders": 1})
    now = datetime.now(timezone.utc)
    dead = plugin_module.normalize_item({
        "title": "Example S01E01 2160p WEB-DL H265", "enclosure": "https://a.example/dead"
    }, now)
    fallback = plugin_module.normalize_item({
        "title": "Example S01E01 1080p WEB-DL H264", "enclosure": "https://b.example/live",
        "pubdate": now - timedelta(hours=2), "seeders": 5,
    }, now)
    plugin._state["managed"]["dead"] = {
        "site_id": "a", "title": dead["title"], "link": dead["enclosure"],
        "media_key": dead["media_key"], "added_at": now.isoformat(),
    }
    plugin._state["dedup_records"][dead["media_key"]] = {
        "title": dead["title"], "resolution_rank": dead["resolution_rank"],
        "quality_rank": dead["quality_rank"],
    }
    plugin._state["dead_seed_watch"]["dead"] = {
        "since": (now - timedelta(minutes=31)).isoformat(), "progress": 0.1,
    }
    plugin._save_fallback_candidate(dead["media_key"], {
        "site": {"id": "b", "name": "Site B"},
        "rule": {"id": "rb", "name": "Task B", "publish_age_to_minutes": 30},
        "item": fallback,
        "url_key": "fallback-url-key",
        "now": now - timedelta(hours=2),
    })

    class FailoverTasks:
        def __init__(self):
            self.added = []
            self.deleted = []
            self.paused = []

        def pause_torrents(self, ids):
            self.paused.extend(ids)
            return True

        def add_torrent(self, **kwargs):
            self.added.append(kwargs)
            return True, ["LIVE"]

        def delete_torrents(self, ids, delete_file=False):
            self.deleted.append((ids, delete_file))
            return True

    adapter = FailoverTasks()
    service = type("Service", (), {"instance": adapter})()
    torrents = [{
        "hash": "dead", "name": dead["title"], "progress": 0.1, "amount_left": 100,
        "dlspeed": 0, "num_seeds": 0,
    }]
    assert plugin._monitor_dead_seeds(service, torrents) == 0
    assert adapter.deleted == []
    assert adapter.paused == ["dead"]
    assert set(plugin._state["managed"]) == {"dead", "live"}
    assert plugin._state["managed"]["dead"]["recovery_state"] == "stalled"
    assert [row["content"] for row in adapter.added] == [fallback["enclosure"]]
    assert plugin._state["dedup_records"][dead["media_key"]]["title"] == fallback["title"]
    assert plugin._state["dedup_records"][dead["media_key"]]["confirmed"] is True


def test_task_label_recovers_managed_torrent_when_qb_name_differs(plugin_module, monkeypatch):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({
        "downloader": "main-qb",
        "sites": [{"id": "a", "name": "A", "rss_rules": [{"id": "r", "name": "A任务"}]}],
    })

    class Tasks:
        def get_torrents(self):
            return [{"hash": "RECOVERED", "name": "Torrent internal name", "tags": "A任务", "progress": 0.2}], False

    service = type("Service", (), {"instance": Tasks()})()
    monkeypatch.setattr(plugin, "_qb_service", lambda *_args, **_kwargs: (service, None))
    rows, error = plugin._site_torrents(plugin._sites[0])
    assert error is None
    assert [row["hash"] for row in rows] == ["RECOVERED"]
    assert plugin._state["managed"] == {}, "GET must not register recovered tasks"
    plugin._recover_managed_by_tags(service.instance.get_torrents()[0])
    assert plugin._state["managed"]["recovered"]["recovered"] is True


def test_unknown_promotion_is_allowed_without_crawling_detail_page(plugin_module, monkeypatch):
    now = datetime.now(timezone.utc)
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({
        "sites": [{
            "id": "a", "name": "A",
            "rss_rules": [{
                "id": "r", "name": "A任务", "url": "https://a.example/rss",
                "promotion": "free_or_2xfree", "publish_age_from_minutes": 0,
                "publish_age_to_minutes": 30,
            }],
        }],
    })

    class Feed:
        def parse(self, **_kwargs):
            return [{
                "title": "New Show S01E01 1080P", "enclosure": "https://a.example/download/1",
                "published_at": now - timedelta(minutes=5),
            }]

    monkeypatch.setattr(plugin_module, "RssHelper", Feed)
    monkeypatch.setattr(plugin, "_fetch_detail_promotion", lambda *_args, **_kwargs: pytest.fail("detail page crawled"))
    downloader = FakeDownloader()
    service = type("Service", (), {"instance": downloader})()
    monkeypatch.setattr(plugin, "_qb_service", lambda *_args, **_kwargs: (service, None))
    result = plugin.run_rss("a")
    assert result["added"] == 1
    assert result["promotion_unknown_allowed"] == 1
    assert plugin._state["site_stats"]["a"]["fetched"] == 1
    assert plugin._state["site_stats"]["a"]["added"] == 1
    plugin.run_rss("a")
    assert plugin._state["site_stats"]["a"]["fetched"] == 1
    assert plugin._state["site_stats"]["a"]["added"] == 0


def test_pending_plugin_task_is_reconciled_and_only_managed_tasks_are_shown(plugin_module, monkeypatch):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({"downloader": "main-qb", "sites": [{"id": "a", "name": "A"}]})
    plugin._state["pending_managed"] = [{
        "site_id": "a", "site_name": "A", "rule_name": "追新", "title": "Show S01E01 1080P",
        "tags": ["追新"], "resolution": "1080P", "promotion": "normal", "free_until": None,
    }]

    class Tasks:
        def get_torrents(self):
            return [
                {"hash": "PLUGIN", "name": "Show S01E01 1080P", "tags": "追新", "progress": 0.5},
                {"hash": "OTHER", "name": "Other task", "tags": "其他", "progress": 1},
            ], False

    service = type("Service", (), {"instance": Tasks()})()
    monkeypatch.setattr(plugin, "_qb_service", lambda *_args, **_kwargs: (service, None))
    rows, error = plugin._site_torrents(plugin._sites[0])
    assert error is None
    assert rows == []
    assert plugin._state["managed"] == {}
    assert len(plugin._state["pending_managed"]) == 1
    plugin._reconcile_pending_managed(service, service.instance.get_torrents()[0])
    rows, error = plugin._site_torrents(plugin._sites[0])
    assert error is None
    assert [row["hash"] for row in rows] == ["PLUGIN"]
    assert "plugin" in plugin._state["managed"]
    assert plugin._state["pending_managed"] == []


def test_unconfirmed_qb_submission_releases_processed_url_for_retry(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    link = "https://tracker.example/download.php?id=missing"
    url_key = plugin_module.hashlib.sha1(link.encode("utf-8")).hexdigest()
    plugin._state["processed_urls"][url_key] = datetime.now(timezone.utc).isoformat()
    plugin._state["pending_managed"] = [{
        "site_id": "a", "rule_name": "追新", "title": "Missing S01E01 2160P",
        "link": link, "url_key": url_key, "existing_hashes": [], "confirm_attempts": 2,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }]
    service = type("Service", (), {"instance": object()})()

    for _ in range(3):
        plugin._reconcile_pending_managed(service, [])
    assert len(plugin._state["pending_managed"]) == 1, "Rapid observations must not expire a new add"
    assert url_key in plugin._state["processed_urls"]
    plugin._state["pending_managed"][0]["added_at"] = (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()
    plugin._reconcile_pending_managed(service, [])

    assert plugin._state["pending_managed"] == []
    assert url_key not in plugin._state["processed_urls"]
    assert plugin._state["history"][-1]["event"] == "retry"


def test_task_name_cannot_be_empty_or_contain_ascii_comma(plugin_module):
    with pytest.raises(ValueError, match="任务名称不能为空"):
        plugin_module.SettingsPayload(sites=[{"name": "A", "rss_rules": [{"name": " "}]}])
    with pytest.raises(ValueError, match="任务名称不能包含英文逗号"):
        plugin_module.SettingsPayload(sites=[{"name": "A", "rss_rules": [{"name": "电影,追新"}]}])


def test_site_name_cannot_be_empty(plugin_module):
    with pytest.raises(ValueError, match="站点名称不能为空"):
        plugin_module.SettingsPayload(sites=[{"name": " "}])


def test_range_start_cannot_exceed_end(plugin_module):
    with pytest.raises(ValueError, match="发种时间范围起点不能大于终点"):
        plugin_module.SettingsPayload(
            sites=[{"name": "A", "rss_rules": [{
                "name": "R1",
                "publish_age_from_value": 2,
                "publish_age_from_unit": "hours",
                "publish_age_to_value": 30,
                "publish_age_to_unit": "minutes",
            }]}]
        )


def test_size_range_validation_compares_different_units(plugin_module):
    with pytest.raises(ValueError, match="文件大小范围起点不能大于终点"):
        plugin_module.SettingsPayload(
            sites=[{"name": "A", "rss_rules": [{
                "name": "R1",
                "size_from_value": 2,
                "size_from_unit": "gib",
                "size_to_value": 1500,
                "size_to_unit": "mib",
            }]}]
        )


def test_state_save_failure_does_not_leave_rss_job_marked_running(plugin_module, monkeypatch):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    monkeypatch.setattr(plugin, "_qb_service", lambda *_args, **_kwargs: (None, "qB 离线"))
    monkeypatch.setattr(plugin, "_save_state", lambda: (_ for _ in ()).throw(RuntimeError("storage offline")))

    first = plugin.run_rss()
    second = plugin.run_rss()

    assert first["error"] == "qB 离线"
    assert second["error"] == "qB 离线"
    assert plugin._running_job_status() == {}


def test_dead_job_owner_allows_next_run_and_old_token_cannot_clear_it(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    plugin._job_timeouts["rss"] = 1
    old_token, _elapsed = plugin._start_job("rss", None)
    plugin._running_jobs["rss"]["started_monotonic"] -= 2
    dead_owner = plugin_module.threading.Thread(target=lambda: None)
    dead_owner.start()
    dead_owner.join()
    plugin._running_jobs["rss"]["owner"] = dead_owner

    new_token, elapsed = plugin._start_job("rss", "site-a")
    plugin._finish_job("rss", old_token)

    assert new_token and new_token != old_token
    assert elapsed == 0
    status = plugin._running_job_status()
    assert status["rss"]["site_id"] == "site-a"
    plugin._finish_job("rss", new_token)
    assert plugin._running_job_status() == {}


def test_active_job_is_still_skipped_before_lease_timeout(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    token, _elapsed = plugin._start_job("free_monitor", None)

    next_token, elapsed = plugin._start_job("free_monitor", None)

    assert next_token is None
    assert elapsed >= 0
    plugin._finish_job("free_monitor", token)


# Business safety contracts, including hooks called by runtime reconciliation.
@pytest.fixture
def business(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    return plugin


def candidate(plugin_module, name="Example S01E01 2160p", url="new", **fields):
    return plugin_module.normalize_item({
        "title": name, "enclosure": f"https://review.invalid/{url}", "size": 1000, **fields,
    })


def managed(plugin, item, **fields):
    return {**plugin._identity_fields(item), "identity_uncertain": False,
            "title": item["title"], "site_id": "a", "download_url": item["enclosure"],
            "recovery_state": "downloading", **fields}


def snapshot(key, item, **fields):
    return {"hash": key, "name": item["title"], "size": item["size"],
            "total_size": item["size"], "progress": 0.2, "amount_left": 800,
            "state": "downloading", "num_seeds": 5, "num_complete": 5,
            "dlspeed": 0, **fields}


@pytest.mark.parametrize("row,complete", [
    ({"progress": 1, "amount_left": 0, "size": 1000}, True),
    ({"progress": 1, "amount_left": 0}, False),
    ({"progress": 1, "amount_left": 0, "size": 0}, False),
    ({"progress": 1, "amount_left": 1, "size": 1000}, False),
    ({"progress": 0.999999, "amount_left": 0, "size": 1000}, False),
    ({"progress": 1, "amount_left": 0, "size": 1000, "state": "checkingUP"}, False),
    ({"progress": 1, "amount_left": 0, "size": 1000, "state": "metaDL"}, False),
    ({"progress": float("nan"), "amount_left": 0, "size": 1000}, False),
    ({"progress": 1, "amount_left": float("inf"), "size": 1000}, False),
    ({"amount_left": 0, "size": 1000, "state": "uploading"}, True),
    ({"amount_left": 0, "size": 1000, "state": "pausedUP"}, True),
    ({"amount_left": 0, "size": 1000, "state": "downloading"}, False),
])
def test_completion_requires_known_size_and_consistent_evidence(business, row, complete):
    assert business._torrent_is_complete(row) is complete


def test_partial_structured_identity_migrates_without_losing_known_fields(plugin_module):
    identity = {"title": "ORIGINAL", "year": 2004, "season": 6,
                "episode_start": 2, "episode_end": 3, "alias": "节目", "identity_version": 1}
    raw = {"title": "Weak qB name 2160p", "identity": identity, "enclosure": "https://review.invalid/x"}
    original = copy.deepcopy(raw)
    item = plugin_module.normalize_item(raw)
    assert raw == original
    assert item["identity"] == {**identity, "identity_version": 2}


def test_ambiguous_legacy_migration_is_non_destructive_and_idempotent(business):
    legacy = {"site_id": "a", "title": "Program S06 2026 2160p", "media_key": "legacy-key"}
    business._state["managed"] = {"one": dict(legacy), "two": dict(legacy)}
    business._state["dedup_records"]["legacy-key"] = {"quality_rank": 999999}
    assert business._migrate_managed_dedup_records()
    first = json.loads(json.dumps(business._state))
    assert all(row["identity_uncertain"] for row in first["managed"].values())
    assert not business._same_media(*first["managed"].values())
    business._state = first
    business._migrate_managed_dedup_records()
    assert all(row["media_key"] == "legacy-key" for row in business._state["managed"].values())
    again = copy.deepcopy(business._state)
    assert business._migrate_managed_dedup_records() is False
    assert business._state == again
    assert business._site_dedup_allows("a", {"media_key": "legacy-key", "quality_rank": 1})


def test_confirm_hook_commits_live_fields_and_exits_pending(business, plugin_module):
    old, new = candidate(plugin_module, "Example S01E01 1080p", "old"), candidate(plugin_module)
    business._state["managed"] = {
        "old": managed(business, old),
        "new": managed(business, new, recovery_state="pending", replace_hashes=["old"], add_token="new-token"),
    }
    paused = []
    service = SimpleNamespace(instance=SimpleNamespace(pause_torrents=lambda ids: paused.extend(ids) or True))
    rows = [snapshot("old", old), snapshot("new", new, num_seeds=7, num_complete=7)]
    business._on_managed_confirmed(service, "new", rows)
    record = business._state["managed"]["new"]
    assert record["recovery_state"] == "downloading"
    assert record["seeders"] == 7
    assert record["replacement_for"] == ["old"]
    assert business._state["managed"]["old"]["paused_by_plugin"] is True
    assert business._state["managed"]["old"]["paused_for"] == "new"
    assert paused == ["old"]
    dedup = business._state["dedup_records"][new["media_key"]]
    assert dedup["confirmed"] is True and dedup["add_token"] == "new-token"
    assert dedup["seeders"] == 7


@pytest.mark.parametrize("other_kind", ["none", "pending", "managed"])
def test_pending_failure_releases_only_its_own_reservation(business, plugin_module, other_kind):
    item = candidate(plugin_module, seeders=5)
    key = hashlib.sha1(item["enclosure"].encode()).hexdigest()
    failed = managed(business, item, url_key=key, add_token="failed", recovery_state="pending")
    business._state["pending_managed"] = [failed]
    business._state["processed_urls"][key] = "reserved"
    if other_kind != "none":
        other = managed(business, item, url_key=key, add_token="successful")
        if other_kind == "pending":
            business._state["pending_managed"].append(other)
        else:
            business._state["managed"]["ok"] = other
            business._commit_confirmed_dedup("ok")
    else:
        business._state["dedup_records"][item["media_key"]] = {"quality_rank": 999999}
    business._on_pending_failed(SimpleNamespace(instance=SimpleNamespace()), failed, [])
    assert (key in business._state["processed_urls"]) is (other_kind != "none")
    if other_kind == "managed":
        assert business._state["dedup_records"][item["media_key"]]["add_token"] == "successful"
        assert not business._site_dedup_allows("a", item)
    else:
        assert item["media_key"] not in business._state["dedup_records"]
        assert business._site_dedup_allows("a", item)


def test_free_expiry_pauses_and_retains_last_copy_idempotently(business, plugin_module, monkeypatch):
    item = candidate(plugin_module)
    deadline = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    business._state["managed"]["only"] = managed(business, item, free_until=deadline)
    row, paused, deleted = snapshot("only", item), [], []

    def pause(ids):
        paused.extend(ids)
        row["state"] = "pausedDL"
        return True

    service = SimpleNamespace(instance=SimpleNamespace(
        get_torrents=lambda: ([copy.deepcopy(row)], False), pause_torrents=pause,
        delete_torrents=lambda **kwargs: deleted.append(kwargs) or True,
    ))
    monkeypatch.setattr(business, "_qb_service", lambda: (service, None))
    first = business.monitor_free_expiry()
    assert not first.get("error") and first["protected"] == 1 and first["paused"] == 1
    assert paused == ["only"] and deleted == [] and "only" in business._state["managed"]
    record = business._state["managed"]["only"]
    assert record["recovery_state"] == "free_expired" and record["paused_by_plugin"]
    assert record["free_until"] == deadline
    second = business.monitor_free_expiry()
    assert not second.get("error") and second["paused"] == 0
    assert paused == ["only"] and deleted == []


def test_failed_resume_never_pauses_the_remaining_active_copy(business, plugin_module):
    high, low = candidate(plugin_module), candidate(plugin_module, "Example S01E01 1080p", "low")
    business._state["managed"] = {
        "high": managed(business, high, paused_by_plugin=True, pause_reason="upgrade"),
        "low": managed(business, low),
    }
    rows = [snapshot("high", high, state="pausedDL"), snapshot("low", low)]
    paused, resumed = [], []
    service = SimpleNamespace(instance=SimpleNamespace(
        get_torrents=lambda: (copy.deepcopy(rows), False),
        resume_torrents=lambda ids: resumed.extend(ids) or False,
        pause_torrents=lambda ids: paused.extend(ids) or True,
        delete_torrents=lambda **_kw: pytest.fail("No complete copy permits deletion"),
    ))
    assert business._deduplicate_managed_torrents(service) == 0
    assert resumed == ["high"] and paused == []
    assert set(business._state["managed"]) == {"high", "low"}


def test_recovery_never_takes_ownership_of_user_pause(business, plugin_module):
    old, new = candidate(plugin_module, "Example S01E01 1080p", "old"), candidate(plugin_module)
    failed = managed(business, new, recovery_state="stalled")
    business._state["managed"] = {"old": managed(business, old), "new": failed}
    service = SimpleNamespace(instance=SimpleNamespace(
        resume_torrents=lambda **_kw: pytest.fail("User pause must not be resumed"),
    ))
    rows = [snapshot("old", old, state="pausedDL"), snapshot("new", new, num_seeds=0, num_complete=0)]
    assert business._restore_replacement(service, failed, rows) is False
    assert not business._state["managed"]["old"].get("paused_by_plugin")


def test_fallback_add_failure_retains_candidate_for_retry(business, plugin_module, monkeypatch):
    low = candidate(plugin_module, "Example S01E01 1080p", "low", seeders=5)
    high = candidate(plugin_module)
    business._save_fallback_candidate(high["media_key"], {
        "site": {"id": "a", "name": "A"}, "rule": {"id": "r", "name": "Task"},
        "item": low, "url_key": "fallback", "now": datetime.now(timezone.utc),
    })
    results = iter([False, True])
    monkeypatch.setattr(business, "_add_item", lambda *_args: next(results))
    record = managed(business, high, recovery_state="stalled")
    assert business._activate_dead_seed_fallback(None, record) is False
    assert len(business._state["dead_seed_fallbacks"][high["media_key"]]) == 1
    assert "fallback" not in business._state["processed_urls"]
    assert business._activate_dead_seed_fallback(None, record) is True
    assert business._state["dead_seed_fallbacks"][high["media_key"]] == []
    assert "fallback" in business._state["processed_urls"]


def test_replacement_finalization_retries_only_failed_hashes(business, plugin_module):
    old, new = candidate(plugin_module, "Example S01E01 1080p", "old"), candidate(plugin_module)
    business._state["managed"] = {
        key: managed(business, old) for key in ("done", "bad", "good")
    }
    business._state["managed"]["new"] = managed(
        business, new, replacement_for=["absent", "done", "bad", "good"])
    rows = [snapshot("new", new, progress=1, amount_left=0, state="uploading"),
            snapshot("done", old, progress=1, amount_left=0, state="uploading"),
            snapshot("bad", old), snapshot("good", old)]
    calls = []

    def delete(ids, delete_file=False):
        calls.append((ids, delete_file))
        if ids == ["bad"] and calls.count((["bad"], True)) == 1:
            raise RuntimeError("temporary qB failure")
        return True

    service = SimpleNamespace(instance=SimpleNamespace(delete_torrents=delete))
    assert business._finalize_replacements(service, rows) == 1
    assert business._state["managed"]["new"]["replacement_for"] == ["bad"]
    assert set(business._state["managed"]) == {"new", "done", "bad"}
    assert business._finalize_replacements(service, rows) == 1
    assert not business._state["managed"]["new"].get("replacement_for")
    assert set(business._state["managed"]) == {"new", "done"}
    assert calls == [(["bad"], True), (["good"], True), (["bad"], True)]


def test_cleanup_scope_follows_stable_rss_ids_without_expanding(business):
    config = {"sites": [{"id": "a", "name": "A", "rss_rules": [
        {"id": "r", "name": "Renamed"}, {"id": "other", "name": "Other"}],
        "cleanup_rules": [{"id": "c", "name": "Clean", "rss_rule_ids": ["r"], "labels": ["Old"]}]}]}
    first = business._normalize_config(config)
    rule = first["sites"][0]["cleanup_rules"][0]
    assert rule["enabled"] is True and rule["labels"] == ["Renamed"] and rule["rss_rule_ids"] == ["r"]
    first["sites"][0]["rss_rules"] = [{"id": "other", "name": "Other"}]
    removed = business._normalize_config(first)["sites"][0]["cleanup_rules"][0]
    assert removed["enabled"] is False and removed["labels"] == [] and removed["scope_error"]
    assert removed["rss_rule_ids"] == ["r"]


def test_only_explicit_all_scope_can_match_all_tags(plugin_module):
    from brushflowtracker.core import first_cleanup_rule
    torrent = {"tags": "Other", "ratio": 2, "seeding_time": 3600}
    assert first_cleanup_rule(torrent, [{"labels": []}]) is None
    assert first_cleanup_rule(torrent, [{"labels": [], "label_scope": "all"}]) is not None
    assert first_cleanup_rule(torrent, [{"labels": [], "label_scope": "all", "scope_error": "invalid"}]) is None

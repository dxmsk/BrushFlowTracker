"""使用最小宿主替身验证 MoviePilot 插件入口契约。"""

from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from types import ModuleType
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
        "/status", "/settings", "/run", "/test-downloader"
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
    assert task["publish_age_from_minutes"] == 0
    assert task["publish_age_to_minutes"] == 30
    assert task["size_from_gib"] == 5
    assert task["size_to_gib"] is None
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
    plugin_module.BrushFlowTracker._log_selection(
        {"name": "站点 A"},
        {"name": "4K 追新"},
        {"title": "Example 2160P", "enclosure": "https://tracker.example/download/2"},
        "排除",
        "命中排除关键词",
    )
    assert "任务=4K 追新" in messages[0]
    assert "名称=Example 2160P" in messages[0]
    assert "链接=https://tracker.example/download/2" in messages[0]
    assert "原因=命中排除关键词" in messages[0]


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


def test_adding_upgrade_removes_inferior_managed_task_and_files(plugin_module):
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

        def add_torrent(self, **_kwargs):
            return True, ["HIGH"]

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
    assert downloader.deleted == [(["low"], True)]
    assert "low" not in plugin._state["managed"]
    assert "high" in plugin._state["managed"]


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
        "site_id": "a", "site_name": "Site A", "rule_id": "r", "rule_name": "Task A",
        "title": standard["title"], "size": standard["size"], "added_at": now.isoformat(),
    }

    class DelayedHashDownloader:
        def __init__(self):
            self.new_visible = False
            self.deleted = []

        def get_torrents(self):
            rows = [{
                "hash": "OLD", "name": standard["title"], "tags": "Task A", "added_on": 1,
            }]
            if self.new_visible:
                rows.append({
                    "hash": "NEW", "name": dolby_vision["title"], "tags": "Task A", "added_on": 2,
                })
            return rows, False

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

    downloader.new_visible = True
    torrents, _failed = downloader.get_torrents()
    plugin._reconcile_pending_managed(service, torrents)

    assert plugin._state["pending_managed"] == []
    assert "new" in plugin._state["managed"]
    assert "old" not in plugin._state["managed"]
    assert downloader.deleted == [(["old"], True)]
    assert [row["hash"] for row in torrents] == ["NEW"]


def test_delayed_upgrade_retries_inferior_task_deletion(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    plugin._state["managed"]["old"] = {"site_id": "a", "title": "Show S01 2160p"}
    plugin._state["pending_managed"] = [{
        "site_id": "a", "rule_name": "Task A", "title": "Show S01 2160p DV",
        "existing_hashes": ["old"], "replace_hashes": ["old"],
    }]

    class RetryDownloader:
        def __init__(self):
            self.attempts = 0

        def delete_torrents(self, ids, delete_file=False):
            self.attempts += 1
            return self.attempts > 1

    downloader = RetryDownloader()
    service = type("SimpleService", (), {"instance": downloader})()
    torrents = [{"hash": "NEW", "name": "Show S01 2160p DV", "tags": "Task A"}]

    plugin._reconcile_pending_managed(service, torrents)
    assert len(plugin._state["pending_managed"]) == 1
    assert "old" in plugin._state["managed"]

    plugin._reconcile_pending_managed(service, torrents)
    assert plugin._state["pending_managed"] == []
    assert "old" not in plugin._state["managed"]
    assert "new" in plugin._state["managed"]


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

        def get_torrents(self):
            return torrents, False

        def delete_torrents(self, ids, delete_file=False):
            self.deleted.extend(ids)
            assert delete_file is True
            return True

    downloader = ExistingDownloader()
    service = type("SimpleService", (), {"instance": downloader})()

    assert plugin._deduplicate_managed_torrents(service, "a") == 2
    assert set(downloader.deleted) == {"sdr", "hdr-small"}
    assert set(plugin._state["managed"]) == {"hdr-large"}


def test_dead_seed_monitor_deletes_stalled_task_and_releases_dedup(plugin_module):
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

        def delete_torrents(self, ids, delete_file=False):
            self.deleted.append((ids, delete_file))
            return True

    adapter = DeadTasks()
    service = type("Service", (), {"instance": adapter})()
    torrents = [{
        "hash": "dead", "name": title, "progress": 0.1, "amount_left": 100,
        "dlspeed": 0, "num_seeds": 0, "num_complete": 0,
    }]
    assert plugin._monitor_dead_seeds(service, torrents, "a") == 1
    assert adapter.deleted == [(["dead"], True)]
    assert "dead" not in plugin._state["managed"]
    assert item["media_key"] not in plugin._state["dedup_records"]


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
        "since": (now - timedelta(minutes=31)).isoformat(), "progress": 0,
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
    assert plugin._monitor_dead_seeds(service, torrents) == 1
    assert [row["content"] for row in adapter.added] == [fallback["enclosure"]]
    assert "live" in plugin._state["managed"]
    assert plugin._state["dedup_records"][dead["media_key"]]["title"] == fallback["title"]


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
    assert [row["hash"] for row in rows] == ["PLUGIN"]
    assert "plugin" in plugin._state["managed"]
    assert plugin._state["pending_managed"] == []


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
            sites=[{"name": "A", "rss_rules": [{"name": "R1", "publish_age_from_minutes": 30, "publish_age_to_minutes": 0}]}]
        )

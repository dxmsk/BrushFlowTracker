"""qB 按 URL 添加会异步失败但仍回 Ok.：确认插件先取种子、再按 infohash 确认。"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from test_plugin_contract import plugin_module  # noqa: F401


SITE = {"id": "a", "name": "Site A", "cookie": "SID=x", "passkey": "pk"}
RULE = {"id": "r", "name": "Task A", "url": "https://pt.invalid/rss"}


def item(module, url="https://pt.invalid/download/1"):
    now = datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc)
    return module.normalize_item(
        {"title": "Example S01E01 2160p WEB-DL", "enclosure": url, "size": 1024}, now
    )


def service(rows=None):
    class Downloader:
        def __init__(self):
            self.rows = list(rows or [])
            self.added = []

        def get_torrents(self):
            return list(self.rows), False

        def add_torrent(self, **kwargs):
            self.added.append(kwargs)
            return True, []

    return SimpleNamespace(instance=Downloader())


def test_torrent_fetch_failure_never_submits_url_to_qb(plugin_module, monkeypatch):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    target = service()

    def fail(*_args, **_kwargs):
        raise plugin_module.TorrentTransportError("下载种子失败：HTTP 403，请检查站点认证和网络")

    monkeypatch.setattr(plugin_module, "prepare_torrent", fail)

    assert plugin._add_item(SITE, RULE, item(plugin_module), target) is False
    assert target.instance.added == []
    assert plugin._state["managed"] == {}
    assert plugin._state["pending_managed"] == []


def test_verified_bytes_are_submitted_and_confirmed_by_infohash(plugin_module, monkeypatch):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    raw = b"d4:infod6:lengthi1024e4:name4:test12:piece lengthi16384e6:pieces40:" + b"0" * 40 + b"ee"
    monkeypatch.setattr(
        plugin_module, "prepare_torrent",
        lambda *a, **k: {"content": raw, "hashes": ["abc123"], "name": "test", "size": 1024,
                         "transport": "torrent_file", "cookie": ""},
    )
    target = service([{"hash": "ABC123", "name": "Example S01E01 2160p WEB-DL",
                       "size": 1024, "progress": 0, "amount_left": 1024, "state": "downloading"}])

    assert plugin._add_item(SITE, RULE, item(plugin_module), target) is True
    assert target.instance.added[0]["content"] == raw
    assert set(plugin._state["managed"]) == {"abc123"}
    assert plugin._state["pending_managed"] == []
    assert plugin._state["history"][-1]["confirmed"] is True


def test_submitted_but_absent_task_stays_pending_without_claiming_success(plugin_module, monkeypatch):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    monkeypatch.setattr(
        plugin_module, "prepare_torrent",
        lambda *a, **k: {"content": b"d4:infoe", "hashes": ["def456"], "name": "", "size": 0,
                         "transport": "torrent_file", "cookie": ""},
    )
    target = service()

    assert plugin._add_item(SITE, RULE, item(plugin_module), target) is True
    assert plugin._state["managed"] == {}
    pending = plugin._state["pending_managed"]
    assert len(pending) == 1 and pending[0]["expected_hashes"] == ["def456"]
    assert plugin._state["history"][-1]["confirmed"] is False
    assert plugin._active_pending_titles() if hasattr(plugin, "_active_pending_titles") else True


def test_reconcile_confirms_by_infohash_even_when_qb_renames_task(plugin_module, monkeypatch):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    monkeypatch.setattr(
        plugin_module, "prepare_torrent",
        lambda *a, **k: {"content": b"x", "hashes": ["deadbeef"], "name": "", "size": 0,
                         "transport": "torrent_file", "cookie": ""},
    )
    target = service()
    assert plugin._add_item(SITE, RULE, item(plugin_module), target)

    # qB 显示名与 RSS 标题完全不同，只靠名称匹配会永远确认不了。
    target.instance.rows = [{"hash": "DEADBEEF", "name": "[Group] 完全不同的释放名",
                             "tags": "Task A", "size": 1024, "progress": 0.1}]
    plugin._reconcile_pending_managed(target, target.instance.rows)

    assert plugin._state["pending_managed"] == []
    assert set(plugin._state["managed"]) == {"deadbeef"}
    assert "expected_hashes" not in plugin._state["managed"]["deadbeef"]


def test_magnet_is_submitted_as_magnet_and_identity_is_known(plugin_module, monkeypatch):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({})
    magnet = "magnet:?xt=urn:btih:" + "b" * 40
    monkeypatch.setattr(
        plugin_module, "prepare_torrent",
        lambda *a, **k: {"content": magnet, "hashes": ["b" * 40], "name": "", "size": 0,
                         "transport": "magnet", "cookie": ""},
    )
    target = service()

    assert plugin._add_item(SITE, RULE, item(plugin_module, magnet), target) is True
    assert target.instance.added[0]["content"] == magnet
    assert plugin._state["pending_managed"][0]["expected_hashes"] == ["b" * 40]

"""使用最小宿主替身验证 MoviePilot 插件入口契约。"""

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


def test_status_exposes_one_shared_downloader_setting(plugin_module):
    plugin = plugin_module.BrushFlowTracker()
    plugin.init_plugin({"downloader": "main-qb", "sites": [{"name": "A"}, {"name": "B"}]})
    response = plugin.get_status()
    assert response.success is True
    assert response.data["settings"]["downloader"] == "main-qb"
    assert len(response.data["sites"]) == 2

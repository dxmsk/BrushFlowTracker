"""MoviePilot v2 刷流追新插件。"""

from __future__ import annotations

import copy
import hashlib
import math
import re
import threading
import time
import traceback
import uuid
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from html import unescape
from types import SimpleNamespace
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from app import schemas
from app.helper.downloader import DownloaderHelper
from app.helper.rss import RssHelper
from app.helper.thread import ThreadHelper
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler

from .core import (
    first_cleanup_rule,
    item_preference,
    item_preference_with_availability,
    isoformat,
    match_rule,
    normalize_item,
    parse_datetime,
    seed_availability,
    split_terms,
)
from .models import DownloaderTestPayload, RunPayload, SettingsPayload
from .persistence import CoalescingWriter
from .snapshots import BatchTorrentView


class _CustomQBAdapter:
    """把 qbittorrent-api 的对象转换为插件现有的 MoviePilot 下载器接口。"""

    def __init__(self, client: Any, save_path: str = ""):
        self.client = client
        self.save_path = save_path

    @staticmethod
    def _value(item: Any, key: str, default: Any = None) -> Any:
        try:
            if hasattr(item, "get"):
                value = item.get(key)
                return default if value is None else value
        except Exception:
            pass
        return getattr(item, key, default)

    def get_torrents(self, tags: Optional[str] = None):
        try:
            kwargs = {"tag": tags} if tags else {}
            rows = list(self.client.torrents_info(**kwargs) or [])
            result = []
            for row in rows:
                data = {}
                for key in (
                    "hash", "name", "size", "total_size", "progress", "state", "ratio",
                    "seeding_time", "dlspeed", "upspeed", "added_on", "amount_left", "tags",
                    "num_seeds", "num_complete", "num_incomplete", "num_leechs",
                ):
                    data[key] = self._value(row, key)
                result.append(data)
            return result, False
        except Exception as err:
            logger.warning(f"刷流追新自定义 qB 查询任务失败：{err}")
            return [], True

    def add_torrent(self, content: str, tag: str = ""):
        try:
            kwargs = {"urls": content, "tags": tag or None}
            if self.save_path:
                kwargs["save_path"] = self.save_path
            response = self.client.torrents_add(**kwargs)
            hashes = self._value(response, "added_torrent_ids", []) or []
            if isinstance(hashes, str):
                hashes = [hashes]
            hashes = [str(value) for value in hashes if value]
            text = str(response or "").casefold()
            return bool(hashes or "ok" in text or "added" in text), hashes
        except Exception as err:
            logger.warning(f"刷流追新自定义 qB 添加任务失败：{err}")
            return False, []

    def delete_torrents(self, ids: List[str], delete_file: bool = False):
        try:
            self.client.torrents_delete(torrent_hashes=ids, delete_files=bool(delete_file))
            return True
        except Exception as err:
            logger.warning(f"刷流追新自定义 qB 删除任务失败：{err}")
            return False

    def pause_torrents(self, ids: List[str]):
        try:
            self.client.torrents_pause(torrent_hashes=ids)
            return True
        except Exception as err:
            logger.warning(f"刷流追新自定义 qB 暂停任务失败：{err}")
            return False

    def resume_torrents(self, ids: List[str]):
        try:
            self.client.torrents_resume(torrent_hashes=ids)
            return True
        except Exception as err:
            logger.warning(f"刷流追新自定义 qB 恢复任务失败：{err}")
            return False


class BrushFlowTracker(_PluginBase):
    """使用一个 qBittorrent 连接管理多站点 RSS 追新与刷流任务。"""

    plugin_name = "刷流追新"
    plugin_desc = "多站点 RSS 选种、最高画质去重、免费期监控与顺序删种"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/seed.png"
    plugin_version = "1.1.25"
    plugin_author = "Codex"
    author_url = "https://github.com/openai"
    plugin_config_prefix = "brushflowtracker_"
    plugin_order = 22
    auth_level = 2

    STATE_KEY = "runtime_state"

    def init_plugin(self, config: dict = None, _normalized: dict = None) -> None:
        """Publish configuration only between runs; never replace an active run's state."""
        raw_config = config or {}
        normalized = _normalized or self._normalize_config(raw_config)
        if not hasattr(self, "_job_guard"):
            self._job_guard = threading.RLock()
            self._running_jobs = {}
            self._pending_config = None
            self._config_revision = 0
            self._active_config_revision = 0
            self._state_writer = CoalescingWriter()
            self._torrent_cache_generation = 0
            self._published_state = {}
        with self._job_guard:
            if normalized != getattr(self, "_requested_config", None):
                self._config_revision += 1
            self._requested_config = copy.deepcopy(normalized)
            if self._running_jobs:
                self._pending_config = (copy.deepcopy(normalized), copy.deepcopy(raw_config))
                if raw_config != normalized:
                    self.update_config(normalized)
                return
            self._apply_config(normalized, raw_config)

    def _apply_config(self, normalized: Dict[str, Any], raw_config: Dict[str, Any]) -> None:
        """Caller owns _job_guard and has no active network worker."""
        self._enabled = normalized["enabled"]
        self._show_sidebar_nav = normalized["show_sidebar_nav"]
        self._downloader = normalized["downloader"]
        self._downloader_mode = normalized.get("downloader_mode", "moviepilot")
        self._highest_resolution_dedup = normalized["highest_resolution_dedup"]
        self._avoid_dead_seeds = normalized["avoid_dead_seeds"]
        self._dead_seed_wait_minutes = normalized["dead_seed_wait_minutes"]
        self._dead_seed_min_seeders = normalized["dead_seed_min_seeders"]
        self._dead_seed_delete_files = normalized["dead_seed_delete_files"]
        self._rss_interval_minutes = normalized["rss_interval_minutes"]
        self._free_monitor_interval_minutes = normalized["free_monitor_interval_minutes"]
        self._cleanup_interval_minutes = normalized["cleanup_interval_minutes"]
        self._request_timeout_seconds = normalized["request_timeout_seconds"]
        self._history_limit = normalized["history_limit"]
        self._sites = normalized["sites"]
        self._config = normalized
        self._site_auth_cache = {}
        # Locks and live state survive ordinary configuration saves.
        rss_rule_count = sum(len(site.get("rss_rules") or []) for site in self._sites)
        self._job_timeouts = {
            "rss": max(300, self._request_timeout_seconds * max(5, rss_rule_count)),
            "free_monitor": max(120, self._request_timeout_seconds * 3),
            "cleanup": max(120, self._request_timeout_seconds * 3),
        }
        if not hasattr(self, "_torrent_cache_lock"):
            self._torrent_cache_lock = threading.Lock()
            self._torrent_cache: Dict[str, Any] = {
                "signature": None, "loaded_monotonic": 0.0, "torrents": [], "failed": True,
            }
        if not hasattr(self, "_custom_qb_cache_lock"):
            self._custom_qb_cache_lock = threading.Lock()
            self._custom_qb_cache: Dict[str, Any] = {
                "signature": None, "loaded_monotonic": 0.0, "service": None,
            }
        if not hasattr(self, "_downloader_options_cached"):
            self._downloader_options_cached: List[Dict[str, str]] = []
            self._downloader_options_cached_at = 0.0
        # Saving settings re-enters init_plugin on the same instance. Reuse the
        # in-memory runtime state instead of reading and rebuilding a large JSON
        # document on every save.
        if not hasattr(self, "_state"):
            state = copy.deepcopy(self.get_data(self.STATE_KEY) or {})
            self._state = {
                "dedup_records": dict(state.get("dedup_records") or {}),
                "processed_urls": dict(state.get("processed_urls") or {}),
                "managed": dict(state.get("managed") or {}),
                "pending_managed": list(state.get("pending_managed") or []),
                "history": list(state.get("history") or []),
                "site_stats": dict(state.get("site_stats") or {}),
                "last_runs": dict(state.get("last_runs") or {}),
                "dead_seed_urls": dict(state.get("dead_seed_urls") or {}),
                "dead_seed_watch": dict(state.get("dead_seed_watch") or {}),
                "dead_seed_fallbacks": dict(state.get("dead_seed_fallbacks") or {}),
                "deleted_hashes": dict(state.get("deleted_hashes") or {}),
            }
        if self._highest_resolution_dedup and self._migrate_managed_dedup_records():
            self._save_state_safely("migration")
        self._active_config_revision = self._config_revision
        self._pending_config = None
        self._published_state = copy.deepcopy(self._state)
        self._invalidate_torrent_cache()
        if raw_config != normalized:
            self.update_config(normalized)

    def get_state(self) -> bool:
        """返回插件是否启用。"""
        return bool(getattr(self, "_enabled", False))

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """声明使用 Vue 联邦组件渲染插件界面。"""
        return "vue", "dist/assets"

    def get_sidebar_nav(self) -> List[Dict[str, Any]]:
        """在整理分组注册刷流追新首页入口。"""
        if not self.get_state() or not self._show_sidebar_nav:
            return []
        return [
            {
                "nav_key": "main",
                "title": "刷流追新",
                "icon": "mdi-rss-box",
                "section": "organize",
                "permission": "manage",
                "order": 46,
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        """注册可独立配置间隔的 RSS、免费期和删种服务。"""
        if not self.get_state():
            return []
        return [
            {
                "id": "RssRefresh",
                "name": "刷流追新 - RSS 刷新",
                "trigger": "interval",
                "func": self.run_rss,
                "kwargs": {"minutes": self._rss_interval_minutes},
            },
            {
                "id": "FreeMonitor",
                "name": "刷流追新 - 免费期监控",
                "trigger": "interval",
                "func": self.monitor_free_expiry,
                "kwargs": {"minutes": self._free_monitor_interval_minutes},
            },
            {
                "id": "Cleanup",
                "name": "刷流追新 - 自动删种",
                "trigger": "interval",
                "func": self.run_cleanup,
                "kwargs": {"minutes": self._cleanup_interval_minutes},
            },
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        """注册首页和配置页所需的受保护 API。"""
        return [
            {"path": "/status", "endpoint": self.get_status, "methods": ["GET"], "auth": "bear", "summary": "获取刷流追新状态"},
            {"path": "/tasks", "endpoint": self.get_tasks, "methods": ["GET"], "auth": "bear", "summary": "获取 qBittorrent 托管任务"},
            {"path": "/settings", "endpoint": self.save_settings, "methods": ["POST"], "auth": "bear", "summary": "保存刷流追新设置"},
            {"path": "/run", "endpoint": self.run_now, "methods": ["POST"], "auth": "bear", "summary": "立即执行任务"},
            {"path": "/test-downloader", "endpoint": self.test_downloader, "methods": ["POST"], "auth": "bear", "summary": "测试 qBittorrent"},
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回 Vue 配置组件的初始配置。"""
        return [], self._config

    def get_page(self) -> List[dict]:
        """详情页面由 Vue 组件通过 API 自行加载。"""
        return []

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """当前插件不注册消息命令。"""
        return []

    def stop_service(self) -> None:
        """插件没有自建线程池，后台任务由宿主调度器统一回收。"""

    def get_status(
        self,
        site_id: Optional[str] = None,
        include_tasks: bool = True,
        include_downloaders: bool = True,
    ) -> schemas.Response:
        """返回全局配置、站点统计和指定站点的 qBittorrent 任务。"""
        with self._job_guard:
            config = copy.deepcopy(self._requested_config)
            pending_config = self._pending_config is not None
            revision = self._config_revision
            active_revision = self._active_config_revision
        state = self._state_view()
        sites = [self._site_summary(site, state) for site in config["sites"]]
        selected_id = site_id or (sites[0]["id"] if sites else None)
        selected = next((site for site in config["sites"] if site["id"] == selected_id), None)
        tasks: List[Dict[str, Any]] = []
        downloader_error = None
        if selected and include_tasks:
            tasks, downloader_error = self._site_torrents(selected)
        return schemas.Response(
            success=True,
            data={
                "settings": config,
                "sites": sites,
                "selected_site": selected,
                "tasks": tasks,
                "history": [row for row in reversed(state["history"]) if not selected_id or row.get("site_id") == selected_id][:100],
                "downloaders": self._downloader_options() if include_downloaders else [],
                "downloader_error": downloader_error,
                "managed_count": len(state["managed"]),
                "dedup_count": len(state["dedup_records"]),
                "running_jobs": self._running_job_status(),
                "last_runs": state["last_runs"],
                "config_pending": pending_config,
                "config_revision": revision,
                "active_config_revision": active_revision,
                "state_save_pending": self._state_writer.dirty,
            },
        )

    def get_tasks(self, site_id: Optional[str] = None, force: bool = False) -> schemas.Response:
        """独立读取实时 qB 任务，使页面和设置无需等待下载器响应。"""
        with self._job_guard:
            config = copy.deepcopy(self._requested_config)
        state = self._state_view()
        selected_id = site_id or (config["sites"][0]["id"] if config.get("sites") else None)
        selected = next((site for site in config["sites"] if site["id"] == selected_id), None)
        tasks: List[Dict[str, Any]] = []
        downloader_error = None
        if selected:
            tasks, downloader_error = self._site_torrents(selected, force=force)
        return schemas.Response(
            success=True,
            data={
                "tasks": tasks,
                "downloader_error": downloader_error,
                "sites": [self._site_summary(site, state) for site in config["sites"]],
            },
        )

    def save_settings(self, payload: SettingsPayload) -> schemas.Response:
        """校验并保存全部全局与站点设置，同时重建宿主定时任务。"""
        config = self._normalize_config(payload.model_dump())
        with self._job_guard:
            self.update_config(config)
            self.init_plugin(config, _normalized=config)
        try:
            ThreadHelper().submit(self._refresh_scheduler)
        except Exception as err:
            logger.warning(f"刷流追新提交定时任务重建失败，将在插件重载后生效：{str(err)}")
        # 保存接口只返回本地数据，不再同步查询 qB。旧版这里查询一次，
        # 前端随后又查询一次，是保存操作明显迟缓的主要原因。
        status = self.get_status(include_tasks=False, include_downloaders=False)
        return schemas.Response(success=True, message="设置已保存", data=status.data)

    def _refresh_scheduler(self) -> None:
        try:
            Scheduler().update_plugin_job(self.__class__.__name__)
        except Exception as err:
            logger.warning(f"刷流追新重建定时任务失败，将在插件重载后生效：{str(err)}")

    def run_now(self, payload: RunPayload) -> schemas.Response:
        """将指定维护操作提交到 MoviePilot 后台线程。"""
        functions = {
            "rss": self.run_rss,
            "free_monitor": self.monitor_free_expiry,
            "cleanup": self.run_cleanup,
        }
        ThreadHelper().submit(functions[payload.operation], payload.site_id)
        return schemas.Response(success=True, message="任务已提交", data={"operation": payload.operation})

    def test_downloader(self, payload: DownloaderTestPayload) -> schemas.Response:
        """验证全局选择的服务确实是可用的 qBittorrent。"""
        test_config = dict(self._config)
        test_config.update(payload.model_dump(exclude_unset=True))
        service, error = self._qb_service(payload.downloader or None, test_config)
        if error:
            return schemas.Response(success=False, message=error)
        torrents, failed = service.instance.get_torrents()
        if failed:
            return schemas.Response(success=False, message="qBittorrent 查询失败，请检查连接配置")
        return schemas.Response(success=True, message="qBittorrent 连接正常", data={"torrent_count": len(torrents or [])})

    def run_rss(self, site_id: Optional[str] = None) -> Dict[str, Any]:
        """抓取启用站点的 RSS，筛选并添加符合条件的种子。"""
        job_token, elapsed = self._start_job("rss", site_id)
        if not job_token:
            logger.info(f"刷流追新 RSS 任务仍在运行（{elapsed} 秒），本轮跳过")
            return {"skipped": True, "running_seconds": elapsed}
        started = datetime.now().astimezone()
        summary = Counter()
        try:
            service, error = self._qb_service()
            if error:
                raise RuntimeError(error)
            # One baseline for the whole RSS batch, followed by one fresh
            # confirmation query. No per-candidate full-queue polling or sleeps.
            real_service = service
            if hasattr(service.instance, "get_torrents"):
                service = SimpleNamespace(instance=BatchTorrentView(service.instance))
            if self._highest_resolution_dedup:
                summary["replaced"] += self._deduplicate_managed_torrents(service, site_id)
            else:
                self._reconcile_pending_managed(service)
            self._pending_candidates = []
            target_sites = self._target_sites(site_id)
            site_results: Dict[str, Counter] = {}
            for site in target_sites:
                site_result = self._scan_site(site, service, defer_add=True)
                site_results[site["id"]] = site_result
                summary.update(site_result)
            summary.update(self._flush_pending_candidates(service))
            if self._state.get("pending_managed") and hasattr(real_service.instance, "get_torrents"):
                torrents, failed = real_service.instance.get_torrents()
                if not failed:
                    self._reconcile_pending_managed(real_service, torrents)
            self._invalidate_torrent_cache()
            for site in target_sites:
                self._update_site_rss_stats(site["id"], site_results.get(site["id"], Counter()))
            self._record_run("rss", site_id, started, dict(summary), None)
            logger.info(f"刷流追新 RSS 完成：读取 {summary['fetched']}，命中 {summary['matched']}，添加 {summary['added']}")
            return dict(summary)
        except Exception as err:
            self._record_run("rss", site_id, started, dict(summary), str(err))
            logger.error(f"刷流追新 RSS 任务失败：{str(err)}\n{traceback.format_exc()}")
            return {**dict(summary), "error": str(err)}
        finally:
            self._finish_job("rss", job_token)

    def monitor_free_expiry(self, site_id: Optional[str] = None) -> Dict[str, Any]:
        """免费到期先停止下载；没有完整副本时只暂停保留数据并尝试回退。"""
        job_token, elapsed = self._start_job("free_monitor", site_id)
        if not job_token:
            logger.info(f"刷流追新免费期监控仍在运行（{elapsed} 秒），本轮跳过")
            return {"skipped": True, "running_seconds": elapsed}
        started = datetime.now().astimezone()
        result = Counter()
        try:
            service, error = self._qb_service()
            if error:
                raise RuntimeError(error)
            torrents, failed = service.instance.get_torrents()
            if failed:
                raise RuntimeError("读取 qBittorrent 任务失败")
            self._reconcile_pending_managed(service, torrents)
            self._recover_managed_by_tags(torrents)
            result["replacement_deleted"] += self._finalize_replacements(service, torrents)
            result["dead_seed_deleted"] += self._monitor_dead_seeds(service, torrents, site_id)
            torrent_map = {str(item.get("hash") or "").lower(): item for item in torrents or []}
            now = datetime.now().astimezone()
            for torrent_hash, record in list(self._state["managed"].items()):
                if site_id and record.get("site_id") != site_id:
                    continue
                deadline = parse_datetime(record.get("free_until"), now)
                if not deadline or deadline > now:
                    continue
                torrent = torrent_map.get(torrent_hash.lower())
                if not torrent:
                    continue
                result["expired"] += 1
                if self._torrent_is_complete(torrent):
                    record["free_until"] = None
                    result["completed"] += 1
                    continue
                record.update(self._identity_fields(self._managed_item(record, torrent)))
                record["recovery_state"] = "free_expired"
                was_paused = self._torrent_paused(torrent)
                if self._pause_managed(service.instance, [torrent_hash], torrents, "free_expired"):
                    result["paused"] += int(not was_paused and self._torrent_paused(torrent))
                else:
                    result["pause_failed"] += 1
                self._rebuild_media_dedup(str(record.get("media_key") or ""), torrents)
                if not self._has_completed_media_copy(record, torrents):
                    result["protected"] += 1
                    if self._restore_replacement(service, record, torrents) or self._activate_dead_seed_fallback(service, record):
                        result["recovered"] += 1
                    logger.info(f"刷流追新免费到期暂停保留最后副本：{record.get('title')}")
                    continue
                if service.instance.delete_torrents(ids=[torrent_hash], delete_file=True):
                    result["deleted"] += 1
                    self._archive_managed(torrent_hash, "免费到期未完成，已删除任务和文件")
                    logger.warning(f"刷流追新删除免费到期未完成任务：{record.get('title')}")
            self._record_run("free_monitor", site_id, started, dict(result), None)
            return dict(result)
        except Exception as err:
            self._record_run("free_monitor", site_id, started, dict(result), str(err))
            logger.error(f"刷流追新免费期监控失败：{str(err)}\n{traceback.format_exc()}")
            return {**dict(result), "error": str(err)}
        finally:
            self._finish_job("free_monitor", job_token)

    def _monitor_dead_seeds(
        self, service: Any, torrents: List[Dict[str, Any]], site_id: Optional[str] = None
    ) -> int:
        """Recover stalled downloads even when deletion of the last copy is forbidden."""
        if not self._avoid_dead_seeds:
            return 0
        now = datetime.now().astimezone()
        watch = self._state.setdefault("dead_seed_watch", {})
        deleted = 0
        active_hashes = set()
        for torrent in torrents or []:
            torrent_hash = str(torrent.get("hash") or "").lower()
            record = self._state["managed"].get(torrent_hash)
            if not torrent_hash or not record:
                continue
            active_hashes.add(torrent_hash)
            if site_id and record.get("site_id") != site_id:
                continue
            record.update(self._identity_fields(self._managed_item(record, torrent)))
            progress = float(torrent.get("progress") or 0)
            speed = int(torrent.get("dlspeed") or 0)
            if self._torrent_is_complete(torrent):
                watch.pop(torrent_hash, None)
                record["recovery_state"] = "complete"
                self._commit_confirmed_dedup(torrent_hash, torrent)
                continue
            if record.get("recovery_state") == "free_expired":
                continue
            if self._torrent_paused(torrent) and record.get("pause_reason") != "dead_seed":
                # Paused upgrades are backups, not stalled downloads; user pauses
                # must never be taken over by the automatic recovery state machine.
                watch.pop(torrent_hash, None)
                continue
            seeds = seed_availability({key: torrent.get(key) for key in ("num_seeds", "num_complete")})
            if seeds is None:
                watch.pop(torrent_hash, None)
                continue
            if seeds >= self._dead_seed_min_seeders or speed > 0:
                watch.pop(torrent_hash, None)
                if not self._torrent_paused(torrent):
                    record["recovery_state"] = "downloading"
                continue
            entry = watch.setdefault(
                torrent_hash,
                {"since": isoformat(now), "progress": progress, "title": record.get("title")},
            )
            if progress > float(entry.get("progress") or 0):
                entry.update(since=isoformat(now), progress=progress)
                continue
            since = parse_datetime(entry.get("since"), now) or now
            if (now - since).total_seconds() < self._dead_seed_wait_minutes * 60:
                continue
            record["recovery_state"] = "stalled"
            record["stalled_at"] = isoformat(now)
            url = str(record.get("download_url") or record.get("link") or "").strip()
            if url:
                self._state.setdefault("dead_seed_urls", {})[hashlib.sha1(url.encode("utf-8")).hexdigest()] = isoformat(now)
            key = str(record.get("media_key") or "")
            self._rebuild_media_dedup(key, torrents)
            if not self._has_completed_media_copy(record, torrents):
                self._pause_managed(service.instance, [torrent_hash], torrents, "dead_seed")
                if not self._restore_replacement(service, record, torrents):
                    self._activate_dead_seed_fallback(service, record)
                logger.info(f"刷流追新保留死种数据并尝试恢复/备用：{record.get('title')}")
                continue
            if not service.instance.delete_torrents(ids=[torrent_hash], delete_file=self._dead_seed_delete_files):
                logger.warning(f"刷流追新死种删除失败：{record.get('title')}")
                continue
            deleted += 1
            watch.pop(torrent_hash, None)
            self._archive_managed(torrent_hash, "已有完整副本，删除持续停滞的死种", site_id=record.get("site_id"))
            self._rebuild_media_dedup(key, torrents)
        for torrent_hash in list(watch):
            if torrent_hash not in active_hashes:
                watch.pop(torrent_hash, None)
        return deleted

    def run_cleanup(self, site_id: Optional[str] = None) -> Dict[str, Any]:
        """按站点配置顺序应用首条命中的自动删种规则。"""
        job_token, elapsed = self._start_job("cleanup", site_id)
        if not job_token:
            logger.info(f"刷流追新删种任务仍在运行（{elapsed} 秒），本轮跳过")
            return {"skipped": True, "running_seconds": elapsed}
        started = datetime.now().astimezone()
        result = Counter()
        try:
            service, error = self._qb_service()
            if error:
                raise RuntimeError(error)
            torrents, failed = service.instance.get_torrents()
            if failed:
                raise RuntimeError("读取 qBittorrent 任务失败")
            self._reconcile_pending_managed(service, torrents)
            self._recover_managed_by_tags(torrents)
            result["replacement_deleted"] += self._finalize_replacements(service, torrents)
            for site in self._target_sites(site_id):
                rules = site.get("cleanup_rules") or []
                if not rules:
                    continue
                for torrent in torrents or []:
                    torrent_hash = str(torrent.get("hash") or "").lower()
                    managed = self._state["managed"].get(torrent_hash)
                    if not managed or managed.get("site_id") != site["id"]:
                        continue
                    rule = first_cleanup_rule(torrent, rules)
                    if not rule:
                        continue
                    if not self._torrent_is_complete(torrent) and not self._has_completed_media_copy(managed, torrents):
                        result["protected"] += 1
                        logger.info(f"刷流追新自动删种保护未完成最后任务：{torrent.get('name')}")
                        continue
                    result["matched"] += 1
                    if service.instance.delete_torrents(ids=[torrent_hash], delete_file=bool(rule.get("delete_files"))):
                        result["deleted"] += 1
                        reason = f"命中删种规则：{rule.get('name')}"
                        self._archive_managed(torrent_hash, reason, torrent=torrent, site_id=site["id"])
                        logger.info(f"刷流追新自动删种：{torrent.get('name')}，{reason}")
            self._record_run("cleanup", site_id, started, dict(result), None)
            return dict(result)
        except Exception as err:
            self._record_run("cleanup", site_id, started, dict(result), str(err))
            logger.error(f"刷流追新自动删种失败：{str(err)}\n{traceback.format_exc()}")
            return {**dict(result), "error": str(err)}
        finally:
            self._finish_job("cleanup", job_token)

    def _scan_site(self, site: Dict[str, Any], service: Any, defer_add: bool = False) -> Counter:
        result = Counter()
        for rule in site.get("rss_rules") or []:
            if not rule.get("enabled") or not rule.get("url"):
                continue
            try:
                auth_site = self._rule_auth_site(site, rule)
                rss_url = self._rss_url(rule["url"], auth_site)
                raw_items = RssHelper().parse(
                    url=rss_url,
                    proxy=bool(auth_site.get("use_proxy")),
                    timeout=self._request_timeout_seconds,
                    ua=auth_site.get("user_agent") or None,
                )
                if raw_items is None:
                    raise RuntimeError("RSS 地址已过期")
                if raw_items is False:
                    raise RuntimeError("RSS 获取或解析失败")
                result["fetched"] += len(raw_items or [])
                now = datetime.now().astimezone()
                candidates = []
                for raw in raw_items or []:
                    item = normalize_item(raw, now)
                    item["url_key"] = hashlib.sha1(item["enclosure"].encode("utf-8")).hexdigest()
                    url_key = item["url_key"]
                    if url_key in self._state.get("dead_seed_urls", {}):
                        result["dead_seed_skipped"] += 1
                        self._log_selection(site, rule, item, "排除", "该下载链接此前判定为死种")
                        continue
                    promotion_filter = rule.get("promotion")
                    matched, reason = match_rule(item, rule, now)
                    if not matched:
                        if (promotion_filter in {"free", "free_or_2xfree", "2xfree"}
                                and reason in {"不是免费种", "不在免费促销期", "不是双倍上传免费种"}):
                            if not item.get("promotion_known"):
                                result["promotion_unknown_allowed"] += 1
                                logger.info(
                                    f"刷流追新无法确认免费状态，按其他筛选条件继续：站点={site.get('name')} | "
                                    f"任务={rule.get('name')} | 名称={item.get('title')} | 链接={item.get('enclosure')}"
                                )
                            else:
                                result[f"filtered:{reason}"] += 1
                                self._log_selection(site, rule, item, "排除", reason)
                                continue
                        else:
                            result[f"filtered:{reason}"] += 1
                            self._log_selection(site, rule, item, "排除", reason)
                            continue
                    candidates.append(item)
                result["matched"] += len(candidates)
                if self._highest_resolution_dedup:
                    highest_candidates = self._choose_best(candidates)
                    selected_urls = {item["enclosure"] for item in highest_candidates}
                    for item in candidates:
                        if item["enclosure"] not in selected_urls:
                            self._save_fallback_candidate(str(item.get("media_key") or ""), {
                                "site": site, "rule": rule, "item": item,
                                "url_key": hashlib.sha1(item["enclosure"].encode("utf-8")).hexdigest(), "now": now,
                            })
                            result["lower_resolution"] += 1
                            self._log_selection(site, rule, item, "排除", "同批已有更可下载或更高画质版本")
                    candidates = highest_candidates
                for item in candidates:
                    url_key = hashlib.sha1(item["enclosure"].encode("utf-8")).hexdigest()
                    if url_key in self._state["processed_urls"]:
                        result["duplicate"] += 1
                        self._log_selection(site, rule, item, "排除", "下载链接已处理")
                        continue
                    if self._highest_resolution_dedup:
                        if not self._site_dedup_allows(site["id"], item):
                            self._save_fallback_candidate(
                                str(item.get("media_key") or ""),
                                {"site": site, "rule": rule, "item": item, "url_key": url_key, "now": now},
                            )
                            result["lower_resolution"] += 1
                            self._log_selection(site, rule, item, "排除", "不高于已下载画质")
                            continue
                    if defer_add:
                        self._pending_candidates.append({
                            "site": site, "rule": rule, "item": item, "url_key": url_key,
                            "now": now, "site_result": result,
                        })
                        continue
                    if self._add_item(site, rule, item, service):
                        result["added"] += 1
                        self._log_selection(site, rule, item, "添加", "符合全部条件")
                        self._state["processed_urls"][url_key] = isoformat(now)
                    else:
                        result["add_failed"] += 1
                        self._log_selection(site, rule, item, "失败", "qBittorrent 添加失败")
            except Exception as err:
                result["rule_errors"] += 1
                logger.error(f"刷流追新站点 [{site['name']}] 规则 [{rule.get('name')}] 失败：{str(err)}")
        if not defer_add:
            self._update_site_rss_stats(site["id"], result)
        return result

    def _update_site_rss_stats(self, site_id: str, result: Counter) -> None:
        defaults = {
            "fetched": 0,
            "matched": 0,
            "added": 0,
            "duplicate": 0,
            "lower_resolution": 0,
            "site_dedup": 0,
            "add_failed": 0,
            "rule_errors": 0,
            "promotion_unknown_allowed": 0,
        }
        self._state["site_stats"][site_id] = {
            "last_rss_at": isoformat(datetime.now().astimezone()),
            **defaults,
            **dict(result),
        }

    def _migrate_managed_dedup_records(self) -> bool:
        """Backfill reliable identity only; pending/ambiguous legacy data is not proof."""
        changed = False
        for managed in list(self._state.get("managed", {}).values()) + list(self._state.get("pending_managed", [])):
            if not managed.get("title"):
                continue
            item = self._managed_item(managed)
            fields = self._identity_fields(item)
            if any(managed.get(key) != value for key, value in fields.items()):
                managed.update(fields)
                changed = True
        # Old quality-only records may have been produced by an unconfirmed add.
        # Keep them for diagnostics, but never trust them for destructive dedup.
        for torrent_hash in self._state.get("managed", {}):
            changed = self._commit_confirmed_dedup(torrent_hash) or changed
        return changed

    def _commit_confirmed_dedup(self, torrent_hash: str, torrent: Optional[Dict[str, Any]] = None) -> bool:
        """Commit a quality record only after a real managed hash is registered."""
        record = self._state.get("managed", {}).get(str(torrent_hash).lower())
        if not record:
            return False
        item = self._managed_item(record, torrent)
        if item.get("identity_uncertain") or self._recovery_blocked(record):
            return False
        record.update(self._identity_fields(item))
        key = self._site_media_key(str(record.get("site_id") or ""), item)
        previous = self._state["dedup_records"].get(key) or {}
        completed = self._torrent_is_complete(torrent)
        candidate = {
            **self._identity_fields(item), "title": item["title"], "confirmed": True,
            "torrent_hash": str(torrent_hash).lower(), "add_token": record.get("add_token"),
            "completed": completed, "updated_at": record.get("added_at"),
        }
        if previous.get("confirmed") and previous.get("identity_version") == 2:
            if previous.get("completed"):
                candidate["completed"] = True
            if previous.get("torrent_hash") != torrent_hash and self._selection_preference(previous) > self._selection_preference(candidate):
                if completed and not previous.get("completed"):
                    previous["completed"] = True
                    return True
                return False
        if previous == candidate:
            return False
        self._state["dedup_records"][key] = candidate
        return True

    def _rebuild_media_dedup(self, key: str, torrents: Optional[List[Dict[str, Any]]] = None) -> None:
        """Recompute one identity after failure, without erasing another successful add."""
        current = self._state["dedup_records"].get(key) or {}
        if current.get("completed") and current.get("confirmed"):
            return
        self._state["dedup_records"].pop(key, None)
        torrent_map = {str(row.get("hash") or "").lower(): row for row in torrents or []}
        for torrent_hash, record in self._state.get("managed", {}).items():
            if self._managed_item(record).get("media_key") == key:
                self._commit_confirmed_dedup(torrent_hash, torrent_map.get(torrent_hash))

    def _on_managed_confirmed(self, service: Any, torrent_hash: str, torrents: Optional[List[Dict[str, Any]]] = None) -> None:
        """Reconcile hook: call AFTER assigning managed[hash], instead of a bare pause."""
        self._state.setdefault("deleted_hashes", {}).pop(str(torrent_hash).lower(), None)
        self._invalidate_torrent_cache()
        record = self._state["managed"][str(torrent_hash).lower()]
        torrent = next((row for row in torrents or []
                        if str(row.get("hash") or "").lower() == str(torrent_hash).lower()), None)
        record.update(self._identity_fields(self._managed_item(record, torrent)))
        if record.get("recovery_state") in {None, "pending"}:
            record["recovery_state"] = "complete" if self._torrent_is_complete(torrent) else "downloading"
        old_hashes = record.pop("replace_hashes", None) or record.get("replacement_for") or []
        old_hashes = [str(value).lower() for value in old_hashes if str(value).lower() != str(torrent_hash).lower()]
        record["replacement_for"] = self._incomplete_replacement_hashes(old_hashes, torrents, record.get("title", ""))
        record["replacement_for"] = [value for value in record["replacement_for"]
                                     if self._same_media(record, self._state["managed"].get(value, {}))]
        if not self._recovery_blocked(record) and not (torrent and self._torrent_paused(torrent)):
            self._pause_managed(service.instance, record["replacement_for"], torrents or [], "upgrade", str(torrent_hash).lower())
        self._commit_confirmed_dedup(str(torrent_hash).lower(), torrent)

    def _on_pending_failed(self, service: Any, record: Dict[str, Any], torrents: Optional[List[Dict[str, Any]]] = None) -> None:
        """Reconcile hook: rollback this add token only, before removing its pending row."""
        token = record.get("add_token")
        url_key = record.get("url_key") or hashlib.sha1(str(record.get("download_url") or record.get("link") or "").encode()).hexdigest()
        others = list(self._state.get("managed", {}).values()) + [row for row in self._state.get("pending_managed", [])
                 if row is not record and (not token or row.get("add_token") != token)]
        if not any(row.get("url_key") == url_key or (row.get("download_url") and
                   hashlib.sha1(str(row["download_url"]).encode()).hexdigest() == url_key) for row in others):
            self._state["processed_urls"].pop(url_key, None)
        self._rebuild_media_dedup(str(record.get("media_key") or ""), torrents)
        self._restore_replacement(service, record, torrents or [])

    @staticmethod
    def _site_media_key(_site_id: str, item: Dict[str, Any]) -> str:
        # Kept as a compatibility helper name; site_id no longer scopes deduplication.
        return str(item.get("media_key") or item.get("enclosure") or "")

    def _site_dedup_allows(self, site_id: str, item: Dict[str, Any]) -> bool:
        record = self._state["dedup_records"].get(self._site_media_key(site_id, item))
        if not record or not record.get("confirmed") or record.get("identity_version") != 2:
            return True
        if record.get("completed"):
            return False
        return self._selection_preference(item) > self._selection_preference(record)

    def _selection_preference(self, item: Dict[str, Any]) -> Tuple[int, ...]:
        if self._avoid_dead_seeds:
            return item_preference_with_availability(item)
        return item_preference(item)

    def _choose_best(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        chosen: Dict[str, Dict[str, Any]] = {}
        order = []
        for item in items:
            key = str(item.get("media_key") or item.get("enclosure") or "")
            if key not in chosen:
                chosen[key] = item
                order.append(key)
            elif self._selection_preference(item) > self._selection_preference(chosen[key]):
                chosen[key] = item
        return [chosen[key] for key in order]

    def _remember_dead_seed_fallbacks(self, grouped: Dict[str, List[Dict[str, Any]]], selected: Dict[str, Dict[str, Any]]) -> None:
        """Persist non-winning candidates so a later dead-seed replacement bypasses RSS age limits."""
        fallback_state = self._state.setdefault("dead_seed_fallbacks", {})
        for key, rows in grouped.items():
            winner = selected.get(key)
            if not winner:
                continue
            for row in rows:
                if row is not winner:
                    self._save_fallback_candidate(key, row)

    def _save_fallback_candidate(self, key: str, row: Dict[str, Any]) -> None:
        """Persist one eligible alternative, capped per media identity."""
        fallback_state = self._state.setdefault("dead_seed_fallbacks", {})
        existing_rows = list(fallback_state.get(key) or [])
        url_key = str(row.get("url_key") or "")
        if not url_key or any(str(item.get("url_key") or "") == url_key for item in existing_rows):
            return
        source_item = row["item"]
        stored_item = {
            key: source_item.get(key)
            for key in (
                "title", "enclosure", "link", "description", "size", "resolution",
                "resolution_rank", "quality_rank", "media_key", "series_alias", "promotion",
                "promotion_known", "seeders", "subtitle", "identity", "identity_version", "identity_uncertain",
            )
        }
        stored_item["pubdate"] = isoformat(source_item.get("pubdate"))
        stored_item["free_until"] = isoformat(source_item.get("free_until"))
        existing_rows.append({
            "site": {"id": row["site"].get("id"), "name": row["site"].get("name")},
            "rule": {"id": row["rule"].get("id"), "name": row["rule"].get("name")},
            "item": stored_item,
            "url_key": url_key,
            "saved_at": isoformat(row.get("now")),
        })
        existing_rows.sort(key=lambda item: self._selection_preference(normalize_item(item["item"])), reverse=True)
        fallback_state[key] = existing_rows[:10]

    def _activate_dead_seed_fallback(self, service: Any, record: Dict[str, Any]) -> bool:
        """Use a saved eligible release without reapplying its expired RSS age window."""
        key = str(record.get("media_key") or "")
        rows = self._state.get("dead_seed_fallbacks", {}).get(key) or []
        now = datetime.now().astimezone()
        occupied = {str(row.get("download_url") or row.get("link") or "")
                    for row in list(self._state["managed"].values()) + list(self._state["pending_managed"])}
        for row in sorted(rows, key=lambda value: self._selection_preference(value["item"]), reverse=True):
            item = normalize_item(row["item"], now)
            if row.get("url_key") in self._state.get("dead_seed_urls", {}) or item.get("enclosure") in occupied:
                continue
            if not self._same_media(record, item) or (item.get("free_until") and item["free_until"] <= now):
                continue
            site = next((site for site in self._sites if site.get("id") == row["site"].get("id")), None)
            if self._sites and not site:
                continue
            rule = next((rule for rule in (site or {}).get("rss_rules", []) if rule.get("id") == row["rule"].get("id")), None)
            if site and (not site.get("enabled", True) or not rule or not rule.get("enabled", True)):
                continue
            if not self._add_item(site or row["site"], rule or row["rule"], item, service):
                logger.warning(f"刷流追新死种备用版本添加失败，保留候选重试：{item.get('title')}")
                return False
            self._state["processed_urls"][row["url_key"]] = isoformat(now)
            self._state["dead_seed_fallbacks"][key] = [value for value in rows if value is not row]
            logger.info(f"刷流追新死种切换备用版本：{item.get('title')}")
            return True
        return False

    def _managed_item(self, record: Dict[str, Any], torrent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """RSS identity is authoritative; a qB rename supplies only live statistics."""
        torrent = torrent or {}
        source = dict(record)
        source["title"] = str(record.get("title") or torrent.get("name") or "").strip()
        source["size"] = torrent.get("size") or torrent.get("total_size") or record.get("size") or 0
        live_seeds = seed_availability({key: torrent.get(key) for key in ("num_seeds", "num_complete")})
        if live_seeds is not None:
            source["seeders"] = live_seeds
        item = normalize_item(source)
        for key in ("quality_rank", "resolution_rank", "resolution"):
            if record.get(key) is not None:
                item[key] = record[key]
        if not isinstance(record.get("identity"), dict):
            # Season-only legacy titles may have lost the episode stored in subtitle.
            identity = item["identity"]
            certain = bool(identity.get("episode_start") is not None or (
                identity.get("year") is not None and identity.get("season") is None
            )) and not record.get("recovered")
            item["identity_uncertain"] = not certain
        else:
            item["identity_uncertain"] = bool(record.get("identity_uncertain"))
        if item["identity_uncertain"] and record.get("media_key"):
            # A second migration/reload must not silently re-key ambiguous data.
            item["media_key"] = record["media_key"]
        return item

    @staticmethod
    def _identity_fields(item: Dict[str, Any]) -> Dict[str, Any]:
        result = {key: item.get(key) for key in (
            "identity", "identity_version", "identity_uncertain", "media_key", "subtitle",
            "description", "series_alias", "resolution", "resolution_rank", "quality_rank", "size", "seeders",
        )}
        identity = result.get("identity")
        if isinstance(identity, dict):
            result["identity"] = dict(identity)
        return result

    def _same_media(self, left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        left_item, right_item = self._managed_item(left), self._managed_item(right)
        return bool(not left_item.get("identity_uncertain") and not right_item.get("identity_uncertain")
                    and left_item.get("media_key") and left_item["media_key"] == right_item.get("media_key"))

    @staticmethod
    def _recovery_blocked(record: Dict[str, Any]) -> bool:
        deadline = parse_datetime(record.get("free_until"))
        return bool(record.get("recovery_state") in {"stalled", "free_expired"}
                    or (deadline and deadline <= datetime.now().astimezone()))

    def _inferior_managed_hashes(self, _site_id: str, item: Dict[str, Any]) -> List[str]:
        """Only confidently identified copies may participate in replacement."""
        key = str(item.get("media_key") or "")
        if not key or item.get("identity_uncertain"):
            return []
        inferior = []
        for torrent_hash, record in self._state.get("managed", {}).items():
            if record.get("media_key") != key or record.get("identity_uncertain"):
                continue
            if self._recovery_blocked(record):
                inferior.append(str(torrent_hash).lower())
                continue
            current = self._managed_item(record)
            if not current.get("media_key") or current["media_key"] != key:
                continue
            if self._selection_preference(item) > self._selection_preference(current):
                inferior.append(str(torrent_hash).lower())
        return inferior

    @staticmethod
    def _torrent_is_complete(torrent: Optional[Dict[str, Any]]) -> bool:
        """Authorize data removal only with non-contradictory proof of completion."""
        if not torrent:
            return False
        state = str(torrent.get("state") or "").casefold()
        if state in {"metadl", "forcedmetadl", "checkingdl", "checkingup", "checkingresumedata", "allocating", "missingfiles", "error", "unknown"}:
            return False
        try:
            progress = float(torrent["progress"]) if torrent.get("progress") is not None else None
            left = float(torrent["amount_left"]) if torrent.get("amount_left") is not None else None
            size_value = torrent.get("total_size") if torrent.get("total_size") is not None else torrent.get("size")
            size = float(size_value) if size_value is not None else None
            if any(value is not None and not math.isfinite(value) for value in (progress, left, size)):
                return False
            if left is not None and left != 0:
                return False
            if progress is not None and progress != 1:
                return False
            if size is None or size <= 0:
                return False
            # A missing/zero size cannot prove that metadata or files exist.
            upload_state = state in {"uploading", "stalledup", "forcedup", "pausedup", "queuedup", "stoppedup"}
            return bool(progress == 1 or (left == 0 and upload_state))
        except (TypeError, ValueError, OverflowError):
            return False

    @staticmethod
    def _pause_torrents(instance: Any, hashes: List[str]) -> bool:
        """Pause old candidates during an upgrade; deletion is deferred until replacement completes."""
        if not hashes:
            return True
        try:
            method = getattr(instance, "pause_torrents", None)
            if callable(method):
                return bool(method(ids=hashes))
            client = getattr(instance, "client", None)
            method = getattr(client, "torrents_pause", None)
            if callable(method):
                method(torrent_hashes=hashes)
                return True
        except Exception as err:
            logger.warning(f"刷流追新暂停旧版本失败：{err}")
        return False

    @staticmethod
    def _torrent_paused(torrent: Dict[str, Any]) -> bool:
        return str(torrent.get("state") or "").casefold().startswith(("paused", "stopped"))

    def _pause_managed(self, instance: Any, hashes: List[str], torrents: List[Dict[str, Any]], reason: str, owner: str = "") -> bool:
        """Record pause ownership only for pauses made by this plugin."""
        torrent_map = {str(row.get("hash") or "").lower(): row for row in torrents}
        success = True
        for torrent_hash in hashes:
            record = self._state["managed"].get(torrent_hash)
            torrent = torrent_map.get(torrent_hash)
            if not record or not torrent or self._torrent_is_complete(torrent):
                continue
            if self._torrent_paused(torrent) and not record.get("paused_by_plugin"):
                continue
            if not self._torrent_paused(torrent) and not self._pause_torrents(instance, [torrent_hash]):
                success = False
                continue
            record.update(paused_by_plugin=True, pause_reason=reason, paused_for=owner)
            torrent["state"] = "pausedDL"
        return success

    def _resume_managed(self, instance: Any, torrent_hash: str, torrent: Dict[str, Any]) -> bool:
        record = self._state["managed"].get(torrent_hash) or {}
        if not record.get("paused_by_plugin") or record.get("pause_reason") != "upgrade" or self._recovery_blocked(record):
            return False
        try:
            method = getattr(instance, "resume_torrents", None)
            if callable(method):
                success = bool(method(ids=[torrent_hash]))
            else:
                method = getattr(getattr(instance, "client", None), "torrents_resume", None)
                if not callable(method):
                    return False
                method(torrent_hashes=[torrent_hash])
                success = True
            if not success:
                return False
            record.update(paused_by_plugin=False, recovery_state="downloading")
            record.pop("pause_reason", None)
            record.pop("paused_for", None)
            torrent["state"] = "downloading"
            return True
        except Exception as err:
            logger.warning(f"刷流追新恢复旧版本失败：{err}")
            return False

    def _restore_replacement(self, service: Any, record: Dict[str, Any], torrents: List[Dict[str, Any]]) -> bool:
        """Resume a viable plugin-owned backup, never a user's paused/free-expired task."""
        torrent_map = {str(row.get("hash") or "").lower(): row for row in torrents}
        choices = []
        for torrent_hash, other in self._state.get("managed", {}).items():
            torrent = torrent_map.get(torrent_hash)
            if other is record or not torrent or not self._same_media(record, other) or self._recovery_blocked(other):
                continue
            if self._torrent_is_complete(torrent):
                return True
            item = self._managed_item(other, torrent)
            if item.get("seeders") == 0:
                continue
            if self._torrent_paused(torrent):
                if not other.get("paused_by_plugin") or other.get("pause_reason") != "upgrade":
                    continue
            else:
                return True
            choices.append((torrent_hash, other, torrent, item))
        choices.sort(key=lambda row: self._selection_preference(row[3]), reverse=True)
        for torrent_hash, other, torrent, _item in choices:
            if self._resume_managed(service.instance, torrent_hash, torrent):
                failed_hashes = [value for value, entry in self._state["managed"].items() if entry is record]
                other["replacement_for"] = list(dict.fromkeys((other.get("replacement_for") or []) + failed_hashes))
                self._rebuild_media_dedup(str(record.get("media_key") or ""), torrents)
                return True
        return False

    @staticmethod
    def _has_completed_in_group(rows: List[Tuple[str, Dict[str, Any], Dict[str, Any]]]) -> bool:
        return any(BrushFlowTracker._torrent_is_complete(row[2]) for row in rows)

    def _incomplete_replacement_hashes(
        self,
        hashes: List[str],
        torrents: Optional[List[Dict[str, Any]]],
        replacement_title: str,
    ) -> List[str]:
        """Never remove completed content as a side effect of quality deduplication."""
        if not hashes:
            return []
        if torrents is None:
            logger.warning(
                f"刷流追新无法确认旧任务完成状态，本轮不删除重复内容：新版本={replacement_title}"
            )
            return []
        torrent_map = {
            str(torrent.get("hash") or "").lower(): torrent
            for torrent in torrents
            if torrent.get("hash")
        }
        deletable = []
        for torrent_hash in hashes:
            torrent = torrent_map.get(str(torrent_hash).lower())
            if torrent and self._torrent_is_complete(torrent):
                logger.info(
                    f"刷流追新保留已下载完成的重复内容：{torrent.get('name')} | 新版本={replacement_title}"
                )
                continue
            # A missing hash no longer exists in qB and does not need deletion.
            if torrent:
                deletable.append(str(torrent_hash).lower())
        return deletable

    def _has_completed_media_copy(self, record: Dict[str, Any], torrents: List[Dict[str, Any]]) -> bool:
        if self._managed_item(record).get("identity_uncertain"):
            return False
        torrent_map = {str(t.get("hash") or "").lower(): t for t in torrents or []}
        return any(
            self._same_media(record, other) and self._torrent_is_complete(torrent_map.get(str(h).lower()))
            for h, other in self._state.get("managed", {}).items()
        )

    def _finalize_replacements(self, service: Any, torrents: List[Dict[str, Any]]) -> int:
        """Finalize each old hash independently; failures retain their retry relation."""
        torrent_map = {str(t.get("hash") or "").lower(): t for t in torrents or []}
        deleted = 0
        for new_hash, record in list(self._state.get("managed", {}).items()):
            old_hashes = list(dict.fromkeys(str(value).lower() for value in record.get("replacement_for") or []))
            if not old_hashes or not self._torrent_is_complete(torrent_map.get(str(new_hash).lower())):
                continue
            self._commit_confirmed_dedup(new_hash, torrent_map[new_hash])
            remaining = []
            for old_hash in old_hashes:
                if old_hash == new_hash:
                    continue
                torrent = torrent_map.get(old_hash)
                if not torrent or self._torrent_is_complete(torrent):
                    continue
                old = self._state["managed"].get(old_hash)
                if not old or not self._same_media(record, old):
                    remaining.append(old_hash)
                    continue
                try:
                    success = service.instance.delete_torrents(ids=[old_hash], delete_file=True)
                except Exception as err:
                    logger.warning(f"刷流追新替换删旧失败，保留重试关系：{err}")
                    success = False
                if not success:
                    remaining.append(old_hash)
                    continue
                deleted += 1
                torrent_map.pop(old_hash, None)
                self._archive_managed(old_hash, f"替代任务已完成，清理旧版本：{record.get('title')}")
            if remaining:
                record["replacement_for"] = remaining
                record["replacement_delete_attempts"] = int(record.get("replacement_delete_attempts") or 0) + 1
            else:
                record.pop("replacement_for", None)
                record.pop("replacement_delete_attempts", None)
        return deleted

    def _deduplicate_managed_torrents(self, service: Any, _site_id: Optional[str] = None) -> int:
        """Keep one best managed qB task globally for each media identity."""
        if not hasattr(service.instance, "get_torrents"):
            return 0
        torrents, failed = service.instance.get_torrents()
        if failed:
            logger.warning("刷流追新读取 qBittorrent 任务失败，本轮跳过存量任务去重")
            return 0
        self._reconcile_pending_managed(service, torrents)
        self._recover_managed_by_tags(torrents)
        torrent_map = {
            str(torrent.get("hash") or "").lower(): torrent
            for torrent in torrents or []
            if torrent.get("hash")
        }
        groups: Dict[str, List[Tuple[str, Dict[str, Any], Dict[str, Any]]]] = {}
        for torrent_hash, record in list(self._state.get("managed", {}).items()):
            torrent = torrent_map.get(str(torrent_hash).lower())
            if not torrent:
                continue
            item = self._managed_item(record, torrent)
            record.update(self._identity_fields(item))
            if item.get("identity_uncertain"):
                continue
            key = self._site_media_key(str(record.get("site_id") or ""), item)
            groups.setdefault(key, []).append((str(torrent_hash).lower(), record, torrent))

        deleted = 0
        for key, rows in groups.items():
            has_completed = self._has_completed_in_group(rows)
            eligible = [row for row in rows if self._torrent_is_complete(row[2]) or not self._recovery_blocked(row[1])]
            if not eligible:
                self._rebuild_media_dedup(key, torrents)
                continue
            winner = max(
                eligible,
                key=lambda row: (
                    self._selection_preference(self._managed_item(row[1], row[2])),
                    float(row[2].get("progress") or 0),
                    int(row[2].get("added_on") or 0),
                ),
            )
            winner_item = self._managed_item(winner[1], winner[2])
            self._state["dedup_records"].pop(key, None)
            self._commit_confirmed_dedup(winner[0], winner[2])
            if has_completed and key in self._state["dedup_records"]:
                self._state["dedup_records"][key]["completed"] = True
            # Resume the selected backup BEFORE pausing other copies. A failed
            # resume or user pause must not leave every incomplete copy paused.
            can_pause_others = not self._torrent_paused(winner[2])
            if not has_completed and not can_pause_others:
                can_pause_others = self._resume_managed(service.instance, winner[0], winner[2])
            for torrent_hash, record, torrent in rows:
                if torrent_hash == winner[0]:
                    continue
                if self._torrent_is_complete(torrent):
                    logger.info(
                        f"刷流追新去重保留已下载完成内容：{record.get('title')} | 最佳版本={winner_item['title']}"
                    )
                    continue
                if not has_completed:
                    if can_pause_others:
                        reason = "dead_seed" if self._recovery_blocked(record) else "upgrade"
                        self._pause_managed(service.instance, [torrent_hash], torrents, reason, winner[0])
                        winner[1]["replacement_for"] = list(dict.fromkeys((winner[1].get("replacement_for") or []) + [torrent_hash]))
                    continue
                if service.instance.delete_torrents(ids=[torrent_hash], delete_file=True):
                    deleted += 1
                    self._archive_managed(
                        torrent_hash,
                        f"同一资源已保留更高画质或更大体积版本：{winner_item['title']}",
                        torrent=torrent,
                        site_id=record.get("site_id"),
                    )
                    logger.info(f"刷流追新去重删除较差版本：{record.get('title')} | 保留={winner_item['title']}")
                else:
                    logger.warning(f"刷流追新去重删除 qBittorrent 任务失败：{record.get('title')}")
        return deleted

    def _flush_pending_candidates(self, service: Any) -> Counter:
        """汇总所有站点候选，每个资源全局只添加一个最佳版本。"""
        result = Counter()
        pending = list(getattr(self, "_pending_candidates", []) or [])
        self._pending_candidates = []
        selected = {}
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        if not self._highest_resolution_dedup:
            selected = {f"{index}:{record['item'].get('enclosure') or index}": record for index, record in enumerate(pending)}
        for record in pending:
            if not self._highest_resolution_dedup:
                break
            item = record["item"]
            key = self._site_media_key(record["site"]["id"], item)
            grouped.setdefault(key, []).append(record)
            previous = selected.get(key)
            if previous is None or self._selection_preference(item) > self._selection_preference(previous["item"]):
                if previous is not None:
                    result["site_dedup"] += 1
                    previous.get("site_result", Counter())["site_dedup"] += 1
                    self._log_selection(previous["site"], previous["rule"], previous["item"], "排除", "所有站点同一资源已保留更高画质或更大体积版本")
                selected[key] = record
            else:
                result["site_dedup"] += 1
                record.get("site_result", Counter())["site_dedup"] += 1
                self._log_selection(record["site"], record["rule"], item, "排除", "所有站点同一资源已保留更高画质或更大体积版本")

        self._remember_dead_seed_fallbacks(grouped, selected)
        for record in selected.values():
            site, rule, item = record["site"], record["rule"], record["item"]
            if self._add_item(site, rule, item, service):
                result["added"] += 1
                record.get("site_result", Counter())["added"] += 1
                self._log_selection(site, rule, item, "添加", "符合全部条件且为所有站点全局最佳版本")
                self._state["processed_urls"][record["url_key"]] = isoformat(record["now"])
            else:
                result["add_failed"] += 1
                record.get("site_result", Counter())["add_failed"] += 1
                self._log_selection(site, rule, item, "失败", "qBittorrent 添加失败")
        return result

    def _fetch_detail_promotion(self, site: Dict[str, Any], raw: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
        """读取 NexusPHP 详情页的免费徽章与剩余时间，弥补 RSS 不返回促销字段的站点。"""
        detail_url = self._detail_url(raw, site)
        if not detail_url:
            return None
        try:
            from app.db.site_oper import SiteOper
            from app.utils.http import RequestUtils

            domain = (urlsplit(detail_url).hostname or "").lower()
            auth_cache = getattr(self, "_site_auth_cache", {})
            auth_key = (domain, str(site.get("cookie") or ""), str(site.get("uid") or ""), str(site.get("passkey") or ""))
            if auth_key not in auth_cache:
                configured = SiteOper().get_by_domain(domain) if domain else None
                auth_cache[auth_key] = (
                    site.get("cookie") or (getattr(configured, "cookie", None) if configured else None),
                    site.get("user_agent") or (getattr(configured, "ua", None) if configured else None),
                    bool(site.get("use_proxy")) if "use_proxy" in site else bool(getattr(configured, "proxy", False)),
                )
                self._site_auth_cache = auth_cache
            cookie, ua, use_proxy = auth_cache[auth_key]
            response = RequestUtils(
                cookies=cookie,
                ua=ua or site.get("user_agent") or None,
                headers={
                    "Referer": site.get("referer") or f"{urlsplit(detail_url).scheme}://{urlsplit(detail_url).netloc}/",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                proxies=self._proxy_config() if use_proxy else None,
                timeout=self._request_timeout_seconds,
            ).get_res(detail_url)
            # requests.Response 在 4xx/5xx 时布尔值为 False，不能误报成“无响应”。
            if response is None:
                logger.warning(f"刷流追新读取详情页免费状态失败：{detail_url} 无响应，请检查站点 Cookie/网络")
                return None
            if getattr(response, "status_code", 200) != 200:
                logger.warning(
                    f"刷流追新读取详情页免费状态失败：{detail_url} HTTP {getattr(response, 'status_code', '?')}，"
                    "请在 MoviePilot 站点管理中更新 Cookie"
                )
                return None
            html = getattr(response, "text", "") or ""
            text = unescape(re.sub(r"<[^>]+>", " ", html))
            detail_item = {"title": raw.get("title", ""), "description": text}
            promotion = normalize_item({**detail_item, "enclosure": raw.get("enclosure") or raw.get("link")}, now)
            return {
                "promotion": promotion["promotion"],
                "free_until": promotion.get("free_until"),
                "promotion_known": True,
            }
        except Exception as err:
            logger.debug(f"刷流追新读取详情页免费状态失败：{detail_url}，{str(err)}")
            return None

    @staticmethod
    def _proxy_config() -> Any:
        """按需读取 MoviePilot 全局代理配置，避免测试环境强依赖 settings。"""
        try:
            from app.core.config import settings
            return settings.PROXY
        except Exception:
            return None

    @staticmethod
    def _detail_url(raw: Dict[str, Any], site: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """优先使用 RSS 详情链接，否则将 NexusPHP download.php 链接转换为 details.php。"""
        link = str(raw.get("link") or "").strip()
        if link and "details.php" in link.lower():
            return BrushFlowTracker._append_site_auth(link, site)
        enclosure = str(raw.get("enclosure") or "").strip()
        parts = urlsplit(link or enclosure)
        if not parts.scheme or not parts.netloc:
            return None
        if "download.php" not in parts.path.lower():
            return None
        query = parse_qs(parts.query)
        torrent_id = (query.get("id") or [None])[0]
        if not torrent_id:
            return None
        detail_pairs = [
            (key, value)
            for key, values in query.items()
            for value in values
            if key.casefold() != "downhash"
        ]
        if not any(key.casefold() == "hit" for key, _value in detail_pairs):
            detail_pairs.append(("hit", "1"))
        return BrushFlowTracker._append_site_auth(
            urlunsplit((parts.scheme, parts.netloc, "/details.php", urlencode(detail_pairs), "")), site
        )

    @staticmethod
    def _append_site_auth(
        url: str, site: Optional[Dict[str, Any]] = None, include_rss_key: bool = False
    ) -> str:
        """为站点请求补齐 uid/passkey，但不覆盖 RSS 地址中已有的身份参数。"""
        if not url or not site:
            return url
        uid = str(site.get("uid") or "").strip()
        passkey = str(site.get("passkey") or "").strip()
        rss_key = str(site.get("rss_key") or "").strip() if include_rss_key else ""
        rss_key_name = str(site.get("rss_key_name") or "rsskey").strip() or "rsskey"
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", rss_key_name):
            rss_key_name = "rsskey"
        if not uid and not passkey and not rss_key:
            return url
        # 兼容用户从站点帮助页复制的占位符 URL。
        for token in ("{uid}", "{UID}", "%UID%", "<uid>"):
            if uid:
                url = url.replace(token, uid)
        for token in ("{passkey}", "{PASSKEY}", "%PASSKEY%", "<passkey>"):
            if passkey:
                url = url.replace(token, passkey)
        rss_placeholder_replaced = False
        for token in ("{rsskey}", "{RSSKEY}", "{rss_key}", "%RSSKEY%", "<rsskey>"):
            if rss_key:
                replaced = token in url
                url = url.replace(token, rss_key)
                rss_placeholder_replaced = rss_placeholder_replaced or replaced
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        keys = {str(key).casefold() for key, _value in pairs}
        if uid and not keys.intersection({"uid", "userid", "user_id"}):
            pairs.append(("uid", uid))
        if passkey and not keys.intersection({"passkey", "pass_key", "authkey"}):
            pairs.append(("passkey", passkey))
        if rss_key and not rss_placeholder_replaced and rss_key_name.casefold() not in keys:
            pairs.append((rss_key_name, rss_key))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))

    @staticmethod
    def _rule_auth_site(site: Dict[str, Any], rule: Dict[str, Any]) -> Dict[str, Any]:
        """合并任务级认证与站点默认认证，任务填写的值优先。"""
        merged = dict(site or {})
        for key in ("uid", "passkey", "rss_key", "rss_key_name", "cookie", "user_agent", "referer"):
            value = str(rule.get(key) or "").strip()
            if value:
                merged[key] = value
        if rule.get("use_proxy") is not None:
            merged["use_proxy"] = bool(rule.get("use_proxy"))
        return merged

    @staticmethod
    def _rss_url(url: str, site: Optional[Dict[str, Any]] = None) -> str:
        return BrushFlowTracker._append_site_auth(url, site, include_rss_key=True)

    def _add_item(self, site: Dict[str, Any], rule: Dict[str, Any], item: Dict[str, Any], service: Any) -> bool:
        # Item is already normalized by _scan_site / _flush_pending_candidates.
        task_name = str(rule.get("name") or "RSS 任务").strip()
        tags = [task_name]
        existing_hashes: Optional[set] = None
        before_add: Optional[List[Dict[str, Any]]] = None
        is_batch = isinstance(service.instance, BatchTorrentView)
        if hasattr(service.instance, "get_torrents"):
            try:
                before_add, failed = service.instance.get_torrents()
                if not failed:
                    existing_hashes = {
                        str(row.get("hash") or "").lower()
                        for row in before_add or []
                        if row.get("hash")
                    }
                else:
                    before_add = None
            except Exception as error:
                before_add = None
                logger.warning(f"刷流追新添加前读取 qB 任务快照失败：{error}")
        # In batch mode the snapshot is stale; refreshing managed from it on
        # every add is O(N×M) for no benefit — reconcile handles it once later.
        if not is_batch:
            for torrent in before_add or []:
                record = self._state["managed"].get(str(torrent.get("hash") or "").lower())
                if record:
                    record.update(self._identity_fields(self._managed_item(record, torrent)))
        inferior_hashes = self._inferior_managed_hashes(site["id"], item) if self._highest_resolution_dedup else []
        success, torrent_ids = service.instance.add_torrent(content=item["enclosure"], tag=task_name)
        if not success:
            return False
        hashes = [str(value).lower() for value in torrent_ids or [] if value]
        if not hashes:
            hashes = self._find_added_hashes(
                service, task_name, item["title"], existing_hashes=existing_hashes
            )
        now = datetime.now().astimezone()
        url_key = str(item.get("url_key") or "") or hashlib.sha1(item["enclosure"].encode("utf-8")).hexdigest()
        record = {
            **self._identity_fields(item),
            "identity_uncertain": bool(item.get("identity_uncertain")),
            "add_token": uuid.uuid4().hex,
            "download_url": item["enclosure"],
            "recovery_state": "downloading" if hashes else "pending",
            "site_id": site["id"],
            "site_name": site["name"],
            "rule_id": rule["id"],
            "rule_name": rule.get("name"),
            "title": item["title"],
            "link": item.get("link") or item.get("enclosure"),
            "resolution": item["resolution"],
            "resolution_rank": item.get("resolution_rank"),
            "quality_rank": item.get("quality_rank"),
            "media_key": item.get("media_key"),
            "series_alias": item.get("series_alias"),
            "description": item.get("description") or item.get("summary") or item.get("subtitle") or "",
            "size": item.get("size") or 0,
            "promotion": item["promotion"],
            "free_until": isoformat(item.get("free_until")),
            "tags": tags,
            "added_at": isoformat(now),
        }
        replace_hashes = self._incomplete_replacement_hashes(
            [torrent_hash for torrent_hash in inferior_hashes if torrent_hash not in set(hashes)],
            before_add,
            item["title"],
        )
        for torrent_hash in hashes:
            managed_record = copy.deepcopy(record)
            if replace_hashes:
                managed_record["replacement_for"] = list(replace_hashes)
            self._state["managed"][torrent_hash] = managed_record
            self._on_managed_confirmed(service, torrent_hash, before_add)
        if not hashes:
            self._state["pending_managed"].append({
                **record,
                "url_key": url_key,
                "confirm_attempts": 0,
                "existing_hashes": sorted(existing_hashes or []),
                "replace_hashes": replace_hashes,
            })
        self._append_history({**record, "event": "added", "torrent_hashes": hashes})
        if replace_hashes and hashes:
            logger.info(f"刷流追新已登记升级关系，等待新版本完成后再删除：{item['title']}")
        if item["promotion"] != "normal" and not item.get("free_until"):
            logger.warning(f"刷流追新已添加免费种但无法识别截止时间：{item['title']}")
        logger.info(f"刷流追新已添加：[{site['name']}] {item['title']} ({item['resolution']})")
        return True

    def _log_selection(
        self,
        site: Dict[str, Any],
        rule: Dict[str, Any],
        item: Dict[str, Any],
        outcome: str,
        reason: str,
    ) -> None:
        """记录每个 RSS 条目的最终筛选结果、名称和下载链接。"""
        clean = lambda value: str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
        size = int(item.get("size") or 0)
        size_text = f"{size / 1024 ** 3:.2f} GiB" if size else "未知"
        rule_summary, actual_summary = self._selection_comparison(rule, item)
        logger.info(
            "刷流追新选种 | "
            f"站点={clean(site.get('name'))} | "
            f"任务={clean(rule.get('name'))} | "
            f"结果={clean(outcome)} | "
            f"原因={clean(reason)} | "
            f"体积={size_text} | "
            f"名称={clean(item.get('title'))} | "
            f"链接={clean(item.get('enclosure'))}"
        )
        selection_record = {
            "site_id": site.get("id"),
            "site_name": site.get("name"),
            "rule_id": rule.get("id"),
            "rule_name": rule.get("name"),
            "title": item.get("title"),
            "link": item.get("link") or item.get("enclosure"),
            "resolution": item.get("resolution"),
            "size": size,
            "event": "selection",
            "outcome": outcome,
            "reason": reason,
            "rule_summary": rule_summary,
            "actual_summary": actual_summary,
        }
        if outcome == "添加":
            for history in reversed(self._state.get("history", [])):
                if history.get("event") == "added" and history.get("title") == item.get("title"):
                    history.update(selection_record)
                    history["event"] = "added"
                    break
            else:
                self._append_history(selection_record)
        else:
            self._append_history(selection_record)

    @staticmethod
    def _selection_comparison(rule: Dict[str, Any], item: Dict[str, Any]) -> Tuple[str, str]:
        """生成人可读的规则与种子实际值对照，供日志页面解释筛选结果。"""
        whitelist = split_terms(rule.get("whitelist_keywords") or rule.get("required_keywords"))
        blacklist = split_terms(rule.get("blacklist_keywords") or rule.get("excluded_keywords"))
        haystack = f"{item.get('title', '')}\n{item.get('description', '')}".casefold()
        whitelist_hits = [term for term in whitelist if term.casefold() in haystack]
        whitelist_missing = [term for term in whitelist if term.casefold() not in haystack]
        blacklist_hits = [term for term in blacklist if term.casefold() in haystack]

        time_units = {"seconds": "秒", "minutes": "分钟", "hours": "小时", "days": "天"}
        size_units = {"kib": "KB", "mib": "MB", "gib": "GB", "tib": "TB"}

        def range_text(prefix: str, unit_names: Dict[str, str], default_unit: str) -> str:
            start = rule.get(f"{prefix}_from_value")
            end = rule.get(f"{prefix}_to_value")
            if start is None and end is None:
                return "不限"
            start_text = "不限" if start is None else f"{start:g} {unit_names.get(str(rule.get(f'{prefix}_from_unit') or default_unit), default_unit)}"
            end_text = "不限" if end is None else f"{end:g} {unit_names.get(str(rule.get(f'{prefix}_to_unit') or default_unit), default_unit)}"
            return f"{start_text} 至 {end_text}"

        promotion_names = {
            "any": "不限", "free": "仅免费", "free_or_2xfree": "免费或双倍上传免费", "2xfree": "仅双倍上传免费",
            "normal": "普通", "unknown": "未知",
        }
        rule_parts = [
            f"白名单(全部包含)={', '.join(whitelist) if whitelist else '不限'}",
            f"黑名单(任一排除)={', '.join(blacklist) if blacklist else '不限'}",
            f"画质={', '.join(rule.get('resolutions') or []) or '不限'}",
            f"发种时间={range_text('publish_age', time_units, 'minutes')}",
            f"体积={range_text('size', size_units, 'gib')}",
            f"促销={promotion_names.get(str(rule.get('promotion') or 'any'), str(rule.get('promotion') or '不限'))}",
        ]

        pubdate = item.get("pubdate")
        age_text = "未知"
        if pubdate:
            age_seconds = max(0, (datetime.now().astimezone() - pubdate).total_seconds())
            if age_seconds < 60:
                age_text = f"{age_seconds:.0f} 秒"
            elif age_seconds < 3600:
                age_text = f"{age_seconds / 60:.1f} 分钟"
            elif age_seconds < 86400:
                age_text = f"{age_seconds / 3600:.1f} 小时"
            else:
                age_text = f"{age_seconds / 86400:.1f} 天"
        size = int(item.get("size") or 0)
        actual_parts = [
            f"白名单命中={', '.join(whitelist_hits) if whitelist_hits else '无'}",
            f"白名单缺失={', '.join(whitelist_missing) if whitelist_missing else '无'}",
            f"黑名单命中={', '.join(blacklist_hits) if blacklist_hits else '无'}",
            f"画质={item.get('resolution') or '未知'}",
            f"发种至今={age_text}",
            f"体积={size / 1024 ** 3:.2f} GB" if size else "体积=未知",
            f"促销={promotion_names.get(str(item.get('promotion') or 'unknown'), str(item.get('promotion') or '未知'))}",
        ]
        return "；".join(rule_parts), "；".join(actual_parts)

    def _find_added_hashes(
        self,
        service: Any,
        task_name: str,
        title: str,
        existing_hashes: Optional[set] = None,
    ) -> List[str]:
        if isinstance(service.instance, BatchTorrentView):
            return []  # One real refresh after the whole batch handles pending rows.
        if not hasattr(service.instance, "get_torrents"):
            return []
        torrents, failed = service.instance.get_torrents()
        if failed:
            return []
        matches = []
        for item in torrents or []:
            torrent_hash = str(item.get("hash") or "").lower()
            if not torrent_hash or (existing_hashes is not None and torrent_hash in existing_hashes):
                continue
            tags = set(split_terms(item.get("tags")))
            name = str(item.get("name") or "").strip()
            if task_name in tags and name and title.strip() and (
                    name == title.strip() or title.strip() in name or name in title.strip()):
                matches.append(item)
        matches.sort(key=lambda item: int(item.get("added_on") or 0), reverse=True)
        return [str(matches[0].get("hash") or "").lower()] if matches else []

    def _site_torrents(
        self, site: Dict[str, Any], force: bool = False
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        service, error = self._qb_service()
        if error:
            return [], error
        torrents, failed = self._ui_torrents(service, force=force)
        if failed:
            return [], "读取 qBittorrent 任务失败"
        # HTTP GET is a view operation: confirmations and recovery run only in
        # background jobs, using fresh downloader observations.
        state = self._state_view()
        site_labels = {str(rule.get("name") or "").strip() for rule in site.get("rss_rules") or []}
        site_labels.discard("")
        other_labels = {
            str(rule.get("name") or "").strip()
            for other in self._sites if other["id"] != site["id"]
            for rule in other.get("rss_rules") or []
        }
        site_labels -= other_labels
        managed_hashes = {
            torrent_hash
            for torrent_hash, record in state["managed"].items()
            if record.get("site_id") == site["id"]
        }
        tombstones = state.get("deleted_hashes", {})
        return [
            {
                "hash": item.get("hash"),
                "name": item.get("name"),
                "size": item.get("size") or item.get("total_size") or 0,
                "progress": round(float(item.get("progress") or 0) * 100, 1),
                "state": item.get("state"),
                "ratio": item.get("ratio") or 0,
                "seeding_time": item.get("seeding_time") or 0,
                "dlspeed": item.get("dlspeed") or 0,
                "upspeed": item.get("upspeed") or 0,
                "num_seeds": item.get("num_seeds"),
                "num_complete": item.get("num_complete"),
                "num_incomplete": item.get("num_incomplete"),
                "tags": split_terms(item.get("tags")),
                "free_until": (state["managed"].get(str(item.get("hash") or "").lower()) or {}).get("free_until"),
                "paused_by_plugin": (state["managed"].get(str(item.get("hash") or "").lower()) or {}).get("paused_by_plugin", False),
                "pause_reason": (state["managed"].get(str(item.get("hash") or "").lower()) or {}).get("pause_reason"),
            }
            for item in torrents or []
            if str(item.get("hash") or "").lower() not in tombstones
            and (str(item.get("hash") or "").lower() in managed_hashes
                 or bool(site_labels.intersection(split_terms(item.get("tags")))))
        ], None

    def _invalidate_torrent_cache(self) -> None:
        with self._torrent_cache_lock:
            self._torrent_cache_generation += 1
            self._torrent_cache = {
                "signature": None, "loaded_monotonic": 0.0, "torrents": [], "failed": True,
            }

    def _ui_torrents(self, service: Any, force: bool = False) -> Tuple[List[Dict[str, Any]], bool]:
        """Cache views only; an older in-flight read cannot overwrite invalidation."""
        signature = (id(service.instance), self._downloader_mode, self._downloader)
        now = time.monotonic()
        with self._torrent_cache_lock:
            generation = self._torrent_cache_generation
            cached = self._torrent_cache
            if (not force and cached.get("signature") == signature
                    and not cached.get("failed")
                    and now - float(cached.get("loaded_monotonic") or 0) < 8):
                return copy.deepcopy(cached.get("torrents") or []), False
        torrents, failed = service.instance.get_torrents()
        if not failed:
            with self._torrent_cache_lock:
                if generation == self._torrent_cache_generation:
                    self._torrent_cache = {
                        "signature": signature,
                        "loaded_monotonic": time.monotonic(),
                        "torrents": copy.deepcopy(torrents or []),
                        "failed": False,
                    }
        return list(torrents or []), bool(failed)

    def _recover_managed_by_tags(self, torrents: List[Dict[str, Any]]) -> None:
        """用任务名称标签恢复旧版本未保存成功的托管 hash。"""
        label_rules: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
        for site in self._sites:
            for rule in site.get("rss_rules") or []:
                label = str(rule.get("name") or "").strip()
                if label:
                    label_rules.setdefault(label, []).append((site, rule))
        changed = False
        for torrent in torrents or []:
            torrent_hash = str(torrent.get("hash") or "").lower()
            if (not torrent_hash or torrent_hash in self._state["managed"]
                    or torrent_hash in self._state.get("deleted_hashes", {})):
                continue
            matches = []
            for tag in split_terms(torrent.get("tags")):
                matches.extend(label_rules.get(tag) or [])
            site_ids = {matched_site["id"] for matched_site, _rule in matches}
            if len(site_ids) != 1 or not matches:
                continue
            matched_site, matched_rule = matches[0]
            self._state["managed"][torrent_hash] = {
                "site_id": matched_site["id"],
                "site_name": matched_site["name"],
                "rule_id": matched_rule["id"],
                "rule_name": matched_rule.get("name"),
                "title": torrent.get("name"),
                "resolution": None,
                "promotion": "unknown",
                "free_until": None,
                "tags": split_terms(torrent.get("tags")),
                "added_at": isoformat(datetime.now().astimezone()),
                "recovered": True,
            }
            changed = True
        if changed:
            self._migrate_managed_dedup_records()
            # A running worker persists once at its transaction boundary; do
            # not launch a snapshot writer while it is still changing state.
            if not self._running_jobs:
                self._save_state_safely("task_recovery")

    def _reconcile_pending_managed(
        self, service: Any, torrents: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """Reconcile fresh background observations; merge by identity, never overwrite new rows."""
        if not self._state.get("pending_managed"):
            return
        if torrents is None:
            torrents, failed = service.instance.get_torrents()
            if failed:
                return
        with self._job_guard:
            pending = list(self._state.get("pending_managed") or [])
        resolved_ids = set()
        claimed = set(self._state.get("managed", {}))
        now = datetime.now().astimezone()
        for record in pending:
            task_name = str(record.get("rule_name") or "").strip()
            title = str(record.get("title") or "").strip()
            existing_hashes = {
                str(value).lower() for value in record.get("existing_hashes") or [] if value
            }
            matched_hash = None
            for item in torrents or []:
                torrent_hash = str(item.get("hash") or "").lower()
                if not torrent_hash or torrent_hash in existing_hashes or torrent_hash in claimed:
                    continue
                tags = set(split_terms(item.get("tags")))
                name = str(item.get("name") or "").strip()
                if task_name in tags and title and name and (name == title or title in name or name in title):
                    matched_hash = torrent_hash
                    if matched_hash:
                        break
            if matched_hash:
                managed_record = dict(record)
                for key in ("existing_hashes", "confirm_attempts", "last_confirm_at"):
                    managed_record.pop(key, None)
                self._state["managed"][matched_hash] = managed_record
                self._state.setdefault("deleted_hashes", {}).pop(matched_hash, None)
                claimed.add(matched_hash)
                resolved_ids.add(id(record))
                hook = getattr(self, "_on_managed_confirmed", None)
                if hook:
                    hook(service, matched_hash, torrents)
                self._invalidate_torrent_cache()
            else:
                added_at = parse_datetime(record.get("added_at"), now)
                age_seconds = max(0, (now - added_at).total_seconds()) if added_at else 0
                last_check = parse_datetime(record.get("last_confirm_at"), now)
                if last_check is None or (now - last_check).total_seconds() >= 15:
                    record["confirm_attempts"] = int(record.get("confirm_attempts") or 0) + 1
                    record["last_confirm_at"] = isoformat(now)
                attempts = int(record.get("confirm_attempts") or 0)
                if age_seconds >= 300 or (attempts >= 3 and age_seconds >= 60):
                    hook = getattr(self, "_on_pending_failed", None)
                    if hook:
                        hook(service, record, torrents)
                    else:
                        url_key = str(record.get("url_key") or "")
                        if url_key:
                            self._state["processed_urls"].pop(url_key, None)
                    resolved_ids.add(id(record))
                    self._append_history({
                        **record, "event": "retry", "outcome": "重试",
                        "reason": "qB 未确认提交，已撤销本次占位，允许后续 RSS 重试",
                    })
                    logger.warning(f"刷流追新未在 qBittorrent 确认到任务，将允许 RSS 重试：{title}")
        if resolved_ids:
            with self._job_guard:
                self._state["pending_managed"] = [
                    row for row in self._state.get("pending_managed", []) if id(row) not in resolved_ids
                ]

    def _qb_service(
        self, downloader: Optional[str] = None, config: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[Any], Optional[str]]:
        active_config = config or self._config
        if active_config.get("downloader_mode", self._downloader_mode) == "custom":
            return self._custom_qb_service(active_config)
        downloader_name = downloader or self._downloader
        if not downloader_name:
            return None, "请先选择一个 qBittorrent 下载器"
        service = DownloaderHelper().get_service(name=downloader_name, type_filter="qbittorrent")
        if not service:
            return None, f"qBittorrent 下载器 [{downloader_name}] 不存在、未启用或连接失败"
        return service, None

    def _custom_qb_service(self, config: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Any], Optional[str]]:
        """创建一次性 qBittorrent Web API 适配器，接口与 MoviePilot 下载器保持一致。"""
        config = config or self._config
        url = str(config.get("custom_qb_url") or "").strip()
        host = str(config.get("custom_qb_host") or "").strip()
        port = int(config.get("custom_qb_port") or 8080)
        if not url:
            url = host or "127.0.0.1"
            if "://" not in url:
                url = f"http://{url}"
            if urlsplit(url).port is None:
                url = f"{url.rstrip('/')}:{port}"
        signature = (
            url,
            str(config.get("custom_qb_username") or ""),
            str(config.get("custom_qb_password") or ""),
            str(config.get("custom_qb_save_path") or ""),
            self._request_timeout_seconds,
        )
        with self._custom_qb_cache_lock:
            cached = self._custom_qb_cache
            if (
                cached.get("signature") == signature
                and cached.get("service") is not None
                and time.monotonic() - float(cached.get("loaded_monotonic") or 0) < 300
            ):
                return cached["service"], None
        try:
            from qbittorrentapi import Client

            client = Client(
                host=url,
                username=str(config.get("custom_qb_username") or ""),
                password=str(config.get("custom_qb_password") or ""),
                VERIFY_WEBUI_CERTIFICATE=False,
                REQUESTS_ARGS={"timeout": (10, self._request_timeout_seconds)},
            )
            client.auth_log_in()
            client.app_version()
            adapter = _CustomQBAdapter(client, str(config.get("custom_qb_save_path") or "").strip())
            service = SimpleNamespace(name="custom-qBittorrent", instance=adapter)
            with self._custom_qb_cache_lock:
                self._custom_qb_cache = {
                    "signature": signature,
                    "loaded_monotonic": time.monotonic(),
                    "service": service,
                }
            return service, None
        except Exception as err:
            logger.warning(f"刷流追新自定义 qBittorrent 连接失败：{err}")
            return None, f"自定义 qBittorrent 连接失败：{err}"

    def _downloader_options(self) -> List[Dict[str, str]]:
        if time.monotonic() - self._downloader_options_cached_at < 30:
            return list(self._downloader_options_cached)
        try:
            services = DownloaderHelper().get_services(type_filter="qbittorrent")
            options = [{"title": name, "value": name} for name in services]
            self._downloader_options_cached = options
            self._downloader_options_cached_at = time.monotonic()
            return list(options)
        except Exception as err:
            logger.warning(f"刷流追新读取 qBittorrent 服务失败：{str(err)}")
            return list(self._downloader_options_cached)

    def _target_sites(self, site_id: Optional[str]) -> List[Dict[str, Any]]:
        return [site for site in self._sites if site.get("enabled") and (not site_id or site["id"] == site_id)]

    def _find_site(self, site_id: Optional[str]) -> Optional[Dict[str, Any]]:
        return next((site for site in self._sites if site["id"] == site_id), None)

    def _site_summary(self, site: Dict[str, Any], state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        state = state if state is not None else self._state_view()
        stats = state["site_stats"].get(site["id"], {})
        return {
            "id": site["id"],
            "name": site["name"],
            "enabled": site["enabled"],
            "rss_rule_count": len(site.get("rss_rules") or []),
            "cleanup_rule_count": len(site.get("cleanup_rules") or []),
            "managed_count": sum(1 for row in state["managed"].values() if row.get("site_id") == site["id"]),
            "stats": stats,
        }

    def _archive_managed(
        self,
        torrent_hash: str,
        reason: str,
        torrent: Optional[Dict[str, Any]] = None,
        site_id: Optional[str] = None,
    ) -> None:
        torrent_hash = torrent_hash.lower()
        record = self._state["managed"].pop(torrent_hash, {})
        self._state.setdefault("deleted_hashes", {})[torrent_hash] = isoformat(datetime.now().astimezone())
        self._invalidate_torrent_cache()
        self._append_history(
            {
                **record,
                "site_id": record.get("site_id") or site_id,
                "title": record.get("title") or (torrent or {}).get("name"),
                "event": "deleted",
                "reason": reason,
                "torrent_hashes": [torrent_hash],
            }
        )

    def _append_history(self, record: Dict[str, Any]) -> None:
        record["time"] = isoformat(datetime.now().astimezone())
        self._state["history"].append(record)
        self._state["history"] = self._state["history"][-self._history_limit :]

    def _record_run(
        self,
        operation: str,
        site_id: Optional[str],
        started: datetime,
        result: Dict[str, Any],
        error: Optional[str],
    ) -> None:
        self._state["last_runs"][f"{operation}:{site_id or 'all'}"] = {
            "operation": operation,
            "site_id": site_id,
            "started_at": isoformat(started),
            "finished_at": isoformat(datetime.now().astimezone()),
            "result": result,
            "error": error,
        }

    def _start_job(self, operation: str, site_id: Optional[str]) -> Tuple[Optional[str], int]:
        """One live mutating worker; a timeout never licenses overlapping side effects."""
        now = time.monotonic()
        with self._job_guard:
            live_ids = {thread.ident for thread in threading.enumerate()}
            for name, current in list(self._running_jobs.items()):
                owner = current.get("owner")
                alive = owner.is_alive() if owner is not None else current.get("thread_id") in live_ids
                if not alive:
                    self._running_jobs.pop(name, None)
                    continue
                elapsed = max(0, int(now - current["started_monotonic"]))
                if elapsed >= self._job_timeouts.get(name, 300) and not current.get("overdue_logged"):
                    current["overdue_logged"] = True
                    logger.warning(f"刷流追新 {name} 已运行 {elapsed} 秒；执行线程仍存活，跳过重入")
                return None, elapsed
            if self._pending_config is not None:
                normalized, raw = self._pending_config
                self._apply_config(normalized, raw)
            self._published_state = copy.deepcopy(self._state)
            token = uuid.uuid4().hex
            self._running_jobs[operation] = {
                "token": token,
                "site_id": site_id,
                "started_monotonic": now,
                "started_at": isoformat(datetime.now().astimezone()),
                "thread_id": threading.get_ident(),
                "owner": threading.current_thread(),
                "config_revision": self._active_config_revision,
            }
            return token, 0

    def _finish_job(self, operation: str, token: str) -> None:
        """Drain the last save before releasing the worker and applying queued settings."""
        with self._job_guard:
            current = self._running_jobs.get(operation)
            if not current or current.get("token") != token:
                return
        applied = False
        try:
            self._save_state_safely(operation)
        finally:
            with self._job_guard:
                current = self._running_jobs.get(operation)
                if current and current.get("token") == token:
                    self._running_jobs.pop(operation, None)
                    if self._pending_config is not None:
                        normalized, raw = self._pending_config
                        self._apply_config(normalized, raw)
                        applied = True
                    else:
                        self._published_state = copy.deepcopy(self._state)
            if applied:
                try:
                    ThreadHelper().submit(self._refresh_scheduler)
                except Exception as err:
                    logger.warning(f"刷流追新应用待生效设置后更新调度失败：{err}")

    def _state_view(self) -> Dict[str, Any]:
        """Read a stable published snapshot while a background worker is mutating state."""
        with self._job_guard:
            state = self._published_state if self._running_jobs else self._state
            return copy.deepcopy(state)

    def _running_job_status(self) -> Dict[str, Dict[str, Any]]:
        """Expose current job leases to the management page and status API."""
        now = time.monotonic()
        with self._job_guard:
            return {
                operation: {
                    "site_id": entry.get("site_id"),
                    "started_at": entry.get("started_at"),
                    "running_seconds": max(0, int(now - entry["started_monotonic"])),
                    "timeout_seconds": self._job_timeouts.get(operation),
                }
                for operation, entry in self._running_jobs.items()
            }

    def _save_state_safely(self, operation: str, retry: int = 0) -> None:
        """A busy writer drains newer save requests; failures retain the dirty revision."""
        try:
            self._state_writer.save(self._save_state)
        except Exception as err:
            logger.error(f"刷流追新 {operation} 状态保存失败：{err}\n{traceback.format_exc()}")
            if retry < 2:
                try:
                    ThreadHelper().submit(self._retry_state_save, operation, retry + 1)
                except Exception as submit_error:
                    logger.warning(f"刷流追新状态补写未提交，后续任务将继续重试：{submit_error}")

    def _retry_state_save(self, operation: str, retry: int) -> None:
        time.sleep(min(4, 2 ** (retry - 1)))
        if self._state_writer.dirty:
            self._save_state_safely(operation, retry)

    def _save_state(self) -> None:
        # The durable store gets an independent JSON-compatible value, not a
        # mutable alias to live runtime state. Never trim the live dict here.
        with self._job_guard:
            foreign_worker = any(
                entry.get("thread_id") != threading.get_ident()
                for entry in self._running_jobs.values()
            )
            source = self._published_state if foreign_worker else self._state
            state = copy.deepcopy(source)
        state["processed_urls"] = dict(list(state["processed_urls"].items())[-20000:])
        state["deleted_hashes"] = dict(list(state.get("deleted_hashes", {}).items())[-20000:])
        self.save_data(self.STATE_KEY, state)

    @staticmethod
    def _normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
        raw_config = copy.deepcopy(config)
        # 兼容早期/手工配置中常见的 qb_mode、qb_url、qb_path 命名。
        if "downloader_mode" not in raw_config and raw_config.get("qb_mode"):
            raw_config["downloader_mode"] = raw_config.get("qb_mode")
        if "custom_qb_url" not in raw_config and raw_config.get("qb_url"):
            raw_config["custom_qb_url"] = raw_config.get("qb_url")
        if "custom_qb_save_path" not in raw_config:
            raw_config["custom_qb_save_path"] = raw_config.get("custom_qb_path", "")
        if raw_config.get("downloader_mode") not in {"moviepilot", "custom"}:
            raw_config["downloader_mode"] = "moviepilot"
        for site in raw_config.get("sites") or []:
            for cleanup in site.get("cleanup_rules") or []:
                if not any(key in cleanup for key in ("labels", "rss_rule_ids", "label_scope")):
                    # Legacy omission freezes the current task set; explicit []
                    # is always empty and must never expand to all remaining tasks.
                    cleanup["labels"] = [rule.get("name") for rule in site.get("rss_rules") or [] if rule.get("name")]
            if "uid" not in site and site.get("site_uid"):
                site["uid"] = site.get("site_uid")
            if "passkey" not in site and site.get("site_passkey"):
                site["passkey"] = site.get("site_passkey")
            for rule in site.get("rss_rules") or []:
                if "whitelist_keywords" not in rule:
                    rule["whitelist_keywords"] = rule.get("required_keywords") or []
                if "blacklist_keywords" not in rule:
                    rule["blacklist_keywords"] = rule.get("excluded_keywords") or []
                rule.pop("required_keywords", None)
                rule.pop("excluded_keywords", None)
                if "publish_age_to_minutes" not in rule and rule.get("max_age_minutes") is not None:
                    rule["publish_age_from_minutes"] = 0
                    rule["publish_age_to_minutes"] = rule.get("max_age_minutes")
                if "size_from_gib" not in rule and rule.get("min_size_gib") is not None:
                    rule["size_from_gib"] = rule.get("min_size_gib")
                    rule["size_to_gib"] = None
                if "publish_age_from_value" not in rule:
                    rule["publish_age_from_value"] = rule.get("publish_age_from_minutes")
                    rule["publish_age_from_unit"] = "minutes"
                if "publish_age_to_value" not in rule:
                    rule["publish_age_to_value"] = rule.get("publish_age_to_minutes")
                    rule["publish_age_to_unit"] = "minutes"
                if "size_from_value" not in rule:
                    rule["size_from_value"] = rule.get("size_from_gib")
                    rule["size_from_unit"] = "gib"
                if "size_to_value" not in rule:
                    rule["size_to_value"] = rule.get("size_to_gib")
                    rule["size_to_unit"] = "gib"
                for legacy_key in (
                    "publish_age_from_minutes", "publish_age_to_minutes", "size_from_gib", "size_to_gib",
                    "max_age_minutes", "min_size_gib",
                ):
                    rule.pop(legacy_key, None)
        data = SettingsPayload(**raw_config).model_dump()
        seen_sites = set()
        for site in data["sites"]:
            site["id"] = site.get("id") or uuid.uuid4().hex
            if site["id"] in seen_sites:
                site["id"] = uuid.uuid4().hex
            seen_sites.add(site["id"])
            seen_rules = set()
            for collection in ("rss_rules", "cleanup_rules"):
                for rule in site[collection]:
                    rule["id"] = rule.get("id") or uuid.uuid4().hex
                    if rule["id"] in seen_rules:
                        rule["id"] = uuid.uuid4().hex
                    seen_rules.add(rule["id"])
            rss_by_id = {rule["id"]: rule for rule in site["rss_rules"]}
            for rule in site["cleanup_rules"]:
                rule["scope_error"] = ""
                if rule.get("label_scope") == "all":
                    rule["labels"] = []
                    rule["rss_rule_ids"] = []
                    continue
                ids = list(dict.fromkeys(split_terms(rule.get("rss_rule_ids"))))
                labels = list(dict.fromkeys(split_terms(rule.get("labels"))))
                if ids:
                    missing = [value for value in ids if value not in rss_by_id]
                    if missing:
                        rule["scope_error"] = "关联的 RSS 任务已删除，请重新选择"
                    rule["labels"] = [rss_by_id[value]["name"] for value in ids if value in rss_by_id]
                else:
                    for label in labels:
                        matches = [row["id"] for row in site["rss_rules"] if row["name"] == label]
                        if len(matches) != 1:
                            rule["scope_error"] = "关联的 RSS 标签已删除或重名，请重新选择"
                        else:
                            ids.append(matches[0])
                rule["rss_rule_ids"] = ids
                if not ids or not labels and not rule.get("labels"):
                    rule["scope_error"] = rule["scope_error"] or "未选择 RSS 任务"
                if rule["scope_error"]:
                    rule["enabled"] = False
        return data

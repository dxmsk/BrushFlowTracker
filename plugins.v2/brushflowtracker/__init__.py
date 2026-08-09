"""MoviePilot v2 刷流追新插件。"""

from __future__ import annotations

import hashlib
import threading
import traceback
import uuid
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app import schemas
from app.helper.downloader import DownloaderHelper
from app.helper.rss import RssHelper
from app.helper.thread import ThreadHelper
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler

from .core import (
    choose_highest,
    dedup_allows,
    first_cleanup_rule,
    isoformat,
    match_rule,
    normalize_item,
    parse_datetime,
    split_terms,
)
from .models import DownloaderTestPayload, RunPayload, SettingsPayload


class BrushFlowTracker(_PluginBase):
    """使用一个 qBittorrent 连接管理多站点 RSS 追新与刷流任务。"""

    plugin_name = "刷流追新"
    plugin_desc = "多站点 RSS 选种、最高画质去重、免费期监控与顺序删种"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/seed.png"
    plugin_version = "1.0.0"
    plugin_author = "Codex"
    author_url = "https://github.com/openai"
    plugin_config_prefix = "brushflowtracker_"
    plugin_order = 22
    auth_level = 2

    GLOBAL_TAG = "刷流追新"
    STATE_KEY = "runtime_state"

    def init_plugin(self, config: dict = None) -> None:
        """读取配置、补齐稳定标识并恢复持久化运行状态。"""
        raw_config = config or {}
        normalized = self._normalize_config(raw_config)
        self._enabled = normalized["enabled"]
        self._show_sidebar_nav = normalized["show_sidebar_nav"]
        self._downloader = normalized["downloader"]
        self._highest_resolution_dedup = normalized["highest_resolution_dedup"]
        self._rss_interval_minutes = normalized["rss_interval_minutes"]
        self._free_monitor_interval_minutes = normalized["free_monitor_interval_minutes"]
        self._cleanup_interval_minutes = normalized["cleanup_interval_minutes"]
        self._request_timeout_seconds = normalized["request_timeout_seconds"]
        self._history_limit = normalized["history_limit"]
        self._sites = normalized["sites"]
        self._config = normalized
        self._rss_lock = threading.Lock()
        self._free_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        state = self.get_data(self.STATE_KEY) or {}
        self._state = {
            "dedup_records": dict(state.get("dedup_records") or {}),
            "processed_urls": dict(state.get("processed_urls") or {}),
            "managed": dict(state.get("managed") or {}),
            "history": list(state.get("history") or []),
            "site_stats": dict(state.get("site_stats") or {}),
            "last_runs": dict(state.get("last_runs") or {}),
        }
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

    def get_status(self, site_id: Optional[str] = None) -> schemas.Response:
        """返回全局配置、站点统计和指定站点的 qBittorrent 任务。"""
        sites = [self._site_summary(site) for site in self._sites]
        selected_id = site_id or (sites[0]["id"] if sites else None)
        selected = self._find_site(selected_id)
        tasks: List[Dict[str, Any]] = []
        downloader_error = None
        if selected:
            tasks, downloader_error = self._site_torrents(selected)
        return schemas.Response(
            success=True,
            data={
                "settings": self._config,
                "sites": sites,
                "selected_site": selected,
                "tasks": tasks,
                "history": [row for row in reversed(self._state["history"]) if not selected_id or row.get("site_id") == selected_id][:100],
                "downloaders": self._downloader_options(),
                "downloader_error": downloader_error,
                "managed_count": len(self._state["managed"]),
                "dedup_count": len(self._state["dedup_records"]),
            },
        )

    def save_settings(self, payload: SettingsPayload) -> schemas.Response:
        """校验并保存全部全局与站点设置，同时重建宿主定时任务。"""
        config = self._normalize_config(payload.model_dump())
        self.update_config(config)
        self.init_plugin(config)
        try:
            Scheduler().update_plugin_job(self.__class__.__name__)
        except Exception as err:
            logger.warning(f"刷流追新重建定时任务失败，将在插件重载后生效：{str(err)}")
        return schemas.Response(success=True, message="设置已保存", data=self.get_status().data)

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
        service, error = self._qb_service(payload.downloader or None)
        if error:
            return schemas.Response(success=False, message=error)
        torrents, failed = service.instance.get_torrents()
        if failed:
            return schemas.Response(success=False, message="qBittorrent 查询失败，请检查连接配置")
        return schemas.Response(success=True, message="qBittorrent 连接正常", data={"torrent_count": len(torrents or [])})

    def run_rss(self, site_id: Optional[str] = None) -> Dict[str, Any]:
        """抓取启用站点的 RSS，筛选并添加符合条件的种子。"""
        if not self._rss_lock.acquire(blocking=False):
            logger.info("刷流追新 RSS 任务仍在运行，本轮跳过")
            return {"skipped": True}
        started = datetime.now().astimezone()
        summary = Counter()
        try:
            service, error = self._qb_service()
            if error:
                raise RuntimeError(error)
            for site in self._target_sites(site_id):
                site_result = self._scan_site(site, service)
                summary.update(site_result)
            self._record_run("rss", site_id, started, dict(summary), None)
            logger.info(f"刷流追新 RSS 完成：读取 {summary['fetched']}，命中 {summary['matched']}，添加 {summary['added']}")
            return dict(summary)
        except Exception as err:
            self._record_run("rss", site_id, started, dict(summary), str(err))
            logger.error(f"刷流追新 RSS 任务失败：{str(err)}\n{traceback.format_exc()}")
            return {**dict(summary), "error": str(err)}
        finally:
            self._save_state()
            self._rss_lock.release()

    def monitor_free_expiry(self, site_id: Optional[str] = None) -> Dict[str, Any]:
        """免费到期时删除尚未完成的托管任务及其未完成文件。"""
        if not self._free_lock.acquire(blocking=False):
            logger.info("刷流追新免费期监控仍在运行，本轮跳过")
            return {"skipped": True}
        started = datetime.now().astimezone()
        result = Counter()
        try:
            service, error = self._qb_service()
            if error:
                raise RuntimeError(error)
            torrents, failed = service.instance.get_torrents(tags=self.GLOBAL_TAG)
            if failed:
                raise RuntimeError("读取 qBittorrent 任务失败")
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
                progress = float(torrent.get("progress") or 0)
                amount_left = int(torrent.get("amount_left") or 0)
                if progress >= 1 and amount_left <= 0:
                    record["free_until"] = None
                    result["completed"] += 1
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
            self._save_state()
            self._free_lock.release()

    def run_cleanup(self, site_id: Optional[str] = None) -> Dict[str, Any]:
        """按站点配置顺序应用首条命中的自动删种规则。"""
        if not self._cleanup_lock.acquire(blocking=False):
            logger.info("刷流追新删种任务仍在运行，本轮跳过")
            return {"skipped": True}
        started = datetime.now().astimezone()
        result = Counter()
        try:
            service, error = self._qb_service()
            if error:
                raise RuntimeError(error)
            torrents, failed = service.instance.get_torrents(tags=self.GLOBAL_TAG)
            if failed:
                raise RuntimeError("读取 qBittorrent 任务失败")
            for site in self._target_sites(site_id):
                rules = site.get("cleanup_rules") or []
                if not rules:
                    continue
                site_tag = self._site_tag(site["id"])
                for torrent in torrents or []:
                    rule = first_cleanup_rule(torrent, rules, site_tag)
                    if not rule:
                        continue
                    result["matched"] += 1
                    torrent_hash = str(torrent.get("hash") or "")
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
            self._save_state()
            self._cleanup_lock.release()

    def _scan_site(self, site: Dict[str, Any], service: Any) -> Counter:
        result = Counter()
        site_stats = self._state["site_stats"].setdefault(site["id"], {})
        for rule in site.get("rss_rules") or []:
            if not rule.get("enabled") or not rule.get("url"):
                continue
            try:
                raw_items = RssHelper().parse(
                    url=rule["url"],
                    proxy=bool(site.get("use_proxy")),
                    timeout=self._request_timeout_seconds,
                    ua=site.get("user_agent") or None,
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
                    matched, reason = match_rule(item, rule, now)
                    if not matched:
                        result[f"filtered:{reason}"] += 1
                        continue
                    candidates.append(item)
                result["matched"] += len(candidates)
                if self._highest_resolution_dedup and not rule.get("resolutions"):
                    candidates = choose_highest(candidates)
                for item in candidates:
                    url_key = hashlib.sha1(item["enclosure"].encode("utf-8")).hexdigest()
                    if url_key in self._state["processed_urls"]:
                        result["duplicate"] += 1
                        continue
                    if self._highest_resolution_dedup and not rule.get("resolutions"):
                        if not dedup_allows(item, self._state["dedup_records"]):
                            result["lower_resolution"] += 1
                            continue
                    if self._add_item(site, rule, item, service):
                        result["added"] += 1
                        self._state["processed_urls"][url_key] = isoformat(now)
                        if self._highest_resolution_dedup and not rule.get("resolutions"):
                            self._state["dedup_records"][item["media_key"]] = {
                                "title": item["title"],
                                "resolution": item["resolution"],
                                "resolution_rank": item["resolution_rank"],
                                "updated_at": isoformat(now),
                            }
                    else:
                        result["add_failed"] += 1
            except Exception as err:
                result["rule_errors"] += 1
                logger.error(f"刷流追新站点 [{site['name']}] 规则 [{rule.get('name')}] 失败：{str(err)}")
        site_stats.update({"last_rss_at": isoformat(datetime.now().astimezone()), **dict(result)})
        return result

    def _add_item(self, site: Dict[str, Any], rule: Dict[str, Any], item: Dict[str, Any], service: Any) -> bool:
        tags = [self.GLOBAL_TAG, self._site_tag(site["id"]), *split_terms(rule.get("tags"))]
        success, torrent_ids = service.instance.add_torrent(content=item["enclosure"], tag=tags)
        if not success:
            return False
        hashes = [str(value).lower() for value in torrent_ids or [] if value]
        if not hashes:
            hashes = self._find_added_hashes(service, site["id"], item["title"])
        now = datetime.now().astimezone()
        record = {
            "site_id": site["id"],
            "site_name": site["name"],
            "rule_id": rule["id"],
            "rule_name": rule.get("name"),
            "title": item["title"],
            "resolution": item["resolution"],
            "promotion": item["promotion"],
            "free_until": isoformat(item.get("free_until")),
            "tags": tags,
            "added_at": isoformat(now),
        }
        for torrent_hash in hashes:
            self._state["managed"][torrent_hash] = dict(record)
        self._append_history({**record, "event": "added", "torrent_hashes": hashes})
        if item["promotion"] != "normal" and not item.get("free_until"):
            logger.warning(f"刷流追新已添加免费种但无法识别截止时间：{item['title']}")
        logger.info(f"刷流追新已添加：[{site['name']}] {item['title']} ({item['resolution']})")
        return True

    def _find_added_hashes(self, service: Any, site_id: str, title: str) -> List[str]:
        torrents, failed = service.instance.get_torrents(tags=self._site_tag(site_id))
        if failed:
            return []
        matches = [item for item in torrents or [] if str(item.get("name") or "").strip() == title.strip()]
        matches.sort(key=lambda item: int(item.get("added_on") or 0), reverse=True)
        return [str(matches[0].get("hash") or "").lower()] if matches else []

    def _site_torrents(self, site: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        service, error = self._qb_service()
        if error:
            return [], error
        torrents, failed = service.instance.get_torrents(tags=self._site_tag(site["id"]))
        if failed:
            return [], "读取 qBittorrent 任务失败"
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
                "tags": split_terms(item.get("tags")),
                "free_until": (self._state["managed"].get(str(item.get("hash") or "").lower()) or {}).get("free_until"),
            }
            for item in torrents or []
        ], None

    def _qb_service(self, downloader: Optional[str] = None) -> Tuple[Optional[Any], Optional[str]]:
        downloader_name = downloader or self._downloader
        if not downloader_name:
            return None, "请先选择一个 qBittorrent 下载器"
        service = DownloaderHelper().get_service(name=downloader_name, type_filter="qbittorrent")
        if not service:
            return None, f"qBittorrent 下载器 [{downloader_name}] 不存在、未启用或连接失败"
        return service, None

    def _downloader_options(self) -> List[Dict[str, str]]:
        try:
            services = DownloaderHelper().get_services(type_filter="qbittorrent")
            return [{"title": name, "value": name} for name in services]
        except Exception as err:
            logger.warning(f"刷流追新读取 qBittorrent 服务失败：{str(err)}")
            return []

    def _target_sites(self, site_id: Optional[str]) -> List[Dict[str, Any]]:
        return [site for site in self._sites if site.get("enabled") and (not site_id or site["id"] == site_id)]

    def _find_site(self, site_id: Optional[str]) -> Optional[Dict[str, Any]]:
        return next((site for site in self._sites if site["id"] == site_id), None)

    def _site_summary(self, site: Dict[str, Any]) -> Dict[str, Any]:
        stats = self._state["site_stats"].get(site["id"], {})
        return {
            "id": site["id"],
            "name": site["name"],
            "enabled": site["enabled"],
            "rss_rule_count": len(site.get("rss_rules") or []),
            "cleanup_rule_count": len(site.get("cleanup_rules") or []),
            "managed_count": sum(1 for row in self._state["managed"].values() if row.get("site_id") == site["id"]),
            "stats": stats,
        }

    @classmethod
    def _site_tag(cls, site_id: str) -> str:
        return f"{cls.GLOBAL_TAG}-站点-{site_id[:12]}"

    def _archive_managed(
        self,
        torrent_hash: str,
        reason: str,
        torrent: Optional[Dict[str, Any]] = None,
        site_id: Optional[str] = None,
    ) -> None:
        record = self._state["managed"].pop(torrent_hash.lower(), {})
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

    def _save_state(self) -> None:
        self._state["processed_urls"] = dict(list(self._state["processed_urls"].items())[-20000:])
        self.save_data(self.STATE_KEY, self._state)

    @staticmethod
    def _normalize_config(config: Dict[str, Any]) -> Dict[str, Any]:
        data = SettingsPayload(**config).model_dump()
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
        return data

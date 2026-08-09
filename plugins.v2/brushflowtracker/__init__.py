"""MoviePilot v2 刷流追新插件。"""

from __future__ import annotations

import copy
import hashlib
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


class BrushFlowTracker(_PluginBase):
    """使用一个 qBittorrent 连接管理多站点 RSS 追新与刷流任务。"""

    plugin_name = "刷流追新"
    plugin_desc = "多站点 RSS 选种、最高画质去重、免费期监控与顺序删种"
    plugin_icon = "https://raw.githubusercontent.com/jxxghp/MoviePilot-Plugins/main/icons/seed.png"
    plugin_version = "1.1.4"
    plugin_author = "Codex"
    author_url = "https://github.com/openai"
    plugin_config_prefix = "brushflowtracker_"
    plugin_order = 22
    auth_level = 2

    STATE_KEY = "runtime_state"

    def init_plugin(self, config: dict = None) -> None:
        """读取配置、补齐稳定标识并恢复持久化运行状态。"""
        raw_config = config or {}
        normalized = self._normalize_config(raw_config)
        self._enabled = normalized["enabled"]
        self._show_sidebar_nav = normalized["show_sidebar_nav"]
        self._downloader = normalized["downloader"]
        self._downloader_mode = normalized.get("downloader_mode", "moviepilot")
        self._highest_resolution_dedup = normalized["highest_resolution_dedup"]
        self._rss_interval_minutes = normalized["rss_interval_minutes"]
        self._free_monitor_interval_minutes = normalized["free_monitor_interval_minutes"]
        self._cleanup_interval_minutes = normalized["cleanup_interval_minutes"]
        self._request_timeout_seconds = normalized["request_timeout_seconds"]
        self._history_limit = normalized["history_limit"]
        self._sites = normalized["sites"]
        self._config = normalized
        self._site_auth_cache = {}
        self._rss_lock = threading.Lock()
        self._free_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        state = self.get_data(self.STATE_KEY) or {}
        self._state = {
            "dedup_records": dict(state.get("dedup_records") or {}),
            "processed_urls": dict(state.get("processed_urls") or {}),
            "managed": dict(state.get("managed") or {}),
            "pending_managed": list(state.get("pending_managed") or []),
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
        if not self._rss_lock.acquire(blocking=False):
            logger.info("刷流追新 RSS 任务仍在运行，本轮跳过")
            return {"skipped": True}
        started = datetime.now().astimezone()
        summary = Counter()
        try:
            service, error = self._qb_service()
            if error:
                raise RuntimeError(error)
            self._pending_candidates = []
            for site in self._target_sites(site_id):
                site_result = self._scan_site(site, service, defer_add=True)
                summary.update(site_result)
            summary.update(self._flush_pending_candidates(service))
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
            torrents, failed = service.instance.get_torrents()
            if failed:
                raise RuntimeError("读取 qBittorrent 任务失败")
            self._reconcile_pending_managed(service, torrents)
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
            torrents, failed = service.instance.get_torrents()
            if failed:
                raise RuntimeError("读取 qBittorrent 任务失败")
            self._reconcile_pending_managed(service, torrents)
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
            self._save_state()
            self._cleanup_lock.release()

    def _scan_site(self, site: Dict[str, Any], service: Any, defer_add: bool = False) -> Counter:
        result = Counter()
        site_stats = self._state["site_stats"].setdefault(site["id"], {})
        for rule in site.get("rss_rules") or []:
            if not rule.get("enabled") or not rule.get("url"):
                continue
            try:
                rss_url = self._rss_url(rule["url"], site)
                raw_items = RssHelper().parse(
                    url=rss_url,
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
                    promotion_filter = rule.get("promotion")
                    if promotion_filter in {"free", "free_or_2xfree", "2xfree"}:
                        pre_matched, pre_reason = match_rule(item, {**rule, "promotion": "any"}, now)
                        if not pre_matched:
                            result[f"filtered:{pre_reason}"] += 1
                            self._log_selection(site, rule, item, "排除", pre_reason)
                            continue
                        if item.get("promotion") == "normal":
                            detail = self._fetch_detail_promotion(site, raw, now)
                            if detail:
                                item = normalize_item({**raw, **detail}, now)
                    matched, reason = match_rule(item, rule, now)
                    if not matched:
                        result[f"filtered:{reason}"] += 1
                        self._log_selection(site, rule, item, "排除", reason)
                        continue
                    candidates.append(item)
                result["matched"] += len(candidates)
                if self._highest_resolution_dedup:
                    highest_candidates = choose_highest(candidates)
                    selected_urls = {item["enclosure"] for item in highest_candidates}
                    for item in candidates:
                        if item["enclosure"] not in selected_urls:
                            result["lower_resolution"] += 1
                            self._log_selection(site, rule, item, "排除", "同批已有同影视的更高或同等优先版本")
                    candidates = highest_candidates
                for item in candidates:
                    url_key = hashlib.sha1(item["enclosure"].encode("utf-8")).hexdigest()
                    if url_key in self._state["processed_urls"]:
                        result["duplicate"] += 1
                        self._log_selection(site, rule, item, "排除", "下载链接已处理")
                        continue
                    if self._highest_resolution_dedup:
                        if not dedup_allows(item, self._state["dedup_records"]):
                            result["lower_resolution"] += 1
                            self._log_selection(site, rule, item, "排除", "不高于已下载画质")
                            continue
                    if defer_add:
                        self._pending_candidates.append({"site": site, "rule": rule, "item": item, "url_key": url_key, "now": now})
                        continue
                    if self._add_item(site, rule, item, service):
                        result["added"] += 1
                        self._log_selection(site, rule, item, "添加", "符合全部条件")
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
                        self._log_selection(site, rule, item, "失败", "qBittorrent 添加失败")
            except Exception as err:
                result["rule_errors"] += 1
                logger.error(f"刷流追新站点 [{site['name']}] 规则 [{rule.get('name')}] 失败：{str(err)}")
        site_stats.update({"last_rss_at": isoformat(datetime.now().astimezone()), **dict(result)})
        return result

    def _flush_pending_candidates(self, service: Any) -> Counter:
        """跨站点汇总候选，只添加每个影视身份的最高画质一个条目。"""
        result = Counter()
        pending = list(getattr(self, "_pending_candidates", []) or [])
        self._pending_candidates = []
        selected = {}
        if not self._highest_resolution_dedup:
            selected = {f"{index}:{record['item'].get('enclosure') or index}": record for index, record in enumerate(pending)}
        for record in pending:
            if not self._highest_resolution_dedup:
                break
            item = record["item"]
            key = str(item.get("media_key") or item.get("enclosure") or "")
            previous = selected.get(key)
            if previous is None or int(item.get("resolution_rank") or 0) > int(previous["item"].get("resolution_rank") or 0):
                if previous is not None:
                    result["global_dedup"] += 1
                    self._log_selection(previous["site"], previous["rule"], previous["item"], "排除", "跨站点同一影视已保留更高分辨率版本")
                selected[key] = record
            else:
                result["global_dedup"] += 1
                self._log_selection(record["site"], record["rule"], item, "排除", "跨站点同一影视已保留更高或同等分辨率版本")

        for record in selected.values():
            site, rule, item = record["site"], record["rule"], record["item"]
            if self._add_item(site, rule, item, service):
                result["added"] += 1
                self._log_selection(site, rule, item, "添加", "符合全部条件且为全站点最高画质")
                self._state["processed_urls"][record["url_key"]] = isoformat(record["now"])
                if self._highest_resolution_dedup:
                    self._state["dedup_records"][item["media_key"]] = {
                        "title": item["title"],
                        "resolution": item["resolution"],
                        "resolution_rank": item["resolution_rank"],
                        "updated_at": isoformat(record["now"]),
                    }
            else:
                result["add_failed"] += 1
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
            if domain not in auth_cache:
                configured = SiteOper().get_by_domain(domain) if domain else None
                auth_cache[domain] = (
                    getattr(configured, "cookie", None) if configured else None,
                    getattr(configured, "ua", None) if configured else None,
                    bool(getattr(configured, "proxy", False)) if configured else bool(site.get("use_proxy")),
                )
                self._site_auth_cache = auth_cache
            cookie, ua, use_proxy = auth_cache[domain]
            response = RequestUtils(
                cookies=cookie,
                ua=ua or site.get("user_agent") or None,
                proxies=self._proxy_config() if use_proxy else None,
                timeout=self._request_timeout_seconds,
            ).get_res(detail_url)
            if not response:
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
            if promotion.get("promotion") == "normal":
                return None
            return {"promotion": promotion["promotion"], "free_until": promotion.get("free_until")}
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
        return BrushFlowTracker._append_site_auth(
            urlunsplit((parts.scheme, parts.netloc, "/details.php", urlencode({"id": torrent_id}), "")), site
        )

    @staticmethod
    def _append_site_auth(url: str, site: Optional[Dict[str, Any]] = None) -> str:
        """为站点请求补齐 uid/passkey，但不覆盖 RSS 地址中已有的身份参数。"""
        if not url or not site:
            return url
        uid = str(site.get("uid") or "").strip()
        passkey = str(site.get("passkey") or "").strip()
        if not uid and not passkey:
            return url
        # 兼容用户从站点帮助页复制的占位符 URL。
        for token in ("{uid}", "{UID}", "%UID%", "<uid>"):
            if uid:
                url = url.replace(token, uid)
        for token in ("{passkey}", "{PASSKEY}", "%PASSKEY%", "<passkey>"):
            if passkey:
                url = url.replace(token, passkey)
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        keys = {str(key).casefold() for key, _value in pairs}
        if uid and not keys.intersection({"uid", "userid", "user_id"}):
            pairs.append(("uid", uid))
        if passkey and not keys.intersection({"passkey", "pass_key", "authkey"}):
            pairs.append(("passkey", passkey))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))

    @staticmethod
    def _rss_url(url: str, site: Optional[Dict[str, Any]] = None) -> str:
        return BrushFlowTracker._append_site_auth(url, site)

    def _add_item(self, site: Dict[str, Any], rule: Dict[str, Any], item: Dict[str, Any], service: Any) -> bool:
        task_name = str(rule.get("name") or "RSS 任务").strip()
        tags = [task_name]
        success, torrent_ids = service.instance.add_torrent(content=item["enclosure"], tag=task_name)
        if not success:
            return False
        hashes = [str(value).lower() for value in torrent_ids or [] if value]
        if not hashes:
            hashes = self._find_added_hashes(service, task_name, item["title"])
        now = datetime.now().astimezone()
        record = {
            "site_id": site["id"],
            "site_name": site["name"],
            "rule_id": rule["id"],
            "rule_name": rule.get("name"),
            "title": item["title"],
            "link": item.get("link") or item.get("enclosure"),
            "resolution": item["resolution"],
            "promotion": item["promotion"],
            "free_until": isoformat(item.get("free_until")),
            "tags": tags,
            "added_at": isoformat(now),
        }
        for torrent_hash in hashes:
            self._state["managed"][torrent_hash] = dict(record)
        if not hashes:
            self._state["pending_managed"].append(dict(record))
        self._append_history({**record, "event": "added", "torrent_hashes": hashes})
        if item["promotion"] != "normal" and not item.get("free_until"):
            logger.warning(f"刷流追新已添加免费种但无法识别截止时间：{item['title']}")
        logger.info(f"刷流追新已添加：[{site['name']}] {item['title']} ({item['resolution']})")
        return True

    @staticmethod
    def _log_selection(
        site: Dict[str, Any],
        rule: Dict[str, Any],
        item: Dict[str, Any],
        outcome: str,
        reason: str,
    ) -> None:
        """记录每个 RSS 条目的最终筛选结果、名称和下载链接。"""
        clean = lambda value: str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
        logger.info(
            "刷流追新选种 | "
            f"站点={clean(site.get('name'))} | "
            f"任务={clean(rule.get('name'))} | "
            f"结果={clean(outcome)} | "
            f"原因={clean(reason)} | "
            f"名称={clean(item.get('title'))} | "
            f"链接={clean(item.get('enclosure'))}"
        )

    def _find_added_hashes(self, service: Any, task_name: str, title: str) -> List[str]:
        # 不依赖 qB 的 tag 过滤参数（旧版 MoviePilot/qB 对 tags 参数支持不一致），
        # 先取全部任务，再按本插件设置的任务标签和名称匹配。
        for _attempt in range(3):
            torrents, failed = service.instance.get_torrents()
            if not failed:
                matches = []
                for item in torrents or []:
                    tags = set(split_terms(item.get("tags")))
                    name = str(item.get("name") or "").strip()
                    if task_name in tags and (name == title.strip() or title.strip() in name or name in title.strip()):
                        matches.append(item)
                matches.sort(key=lambda item: int(item.get("added_on") or 0), reverse=True)
                if matches:
                    return [str(matches[0].get("hash") or "").lower()]
            if _attempt < 2:
                time.sleep(0.4)
        return []

    def _site_torrents(self, site: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        service, error = self._qb_service()
        if error:
            return [], error
        torrents, failed = service.instance.get_torrents()
        if failed:
            return [], "读取 qBittorrent 任务失败"
        self._reconcile_pending_managed(service, torrents)
        managed_hashes = {
            torrent_hash
            for torrent_hash, record in self._state["managed"].items()
            if record.get("site_id") == site["id"]
        }
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
            if str(item.get("hash") or "").lower() in managed_hashes
        ], None

    def _reconcile_pending_managed(
        self, service: Any, torrents: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """补登记 qB 添加接口未立即返回 hash 的插件任务。"""
        pending = list(self._state.get("pending_managed") or [])
        if not pending:
            return
        if torrents is None:
            torrents, failed = service.instance.get_torrents()
            if failed:
                return
        remaining = []
        for record in pending:
            task_name = str(record.get("rule_name") or "").strip()
            title = str(record.get("title") or "").strip()
            matched_hash = None
            for item in torrents or []:
                tags = set(split_terms(item.get("tags")))
                name = str(item.get("name") or "").strip()
                if task_name in tags and title and (name == title or title in name or name in title):
                    matched_hash = str(item.get("hash") or "").lower()
                    if matched_hash:
                        break
            if matched_hash:
                self._state["managed"][matched_hash] = dict(record)
            else:
                remaining.append(record)
        self._state["pending_managed"] = remaining

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
            return SimpleNamespace(name="custom-qBittorrent", instance=adapter), None
        except Exception as err:
            logger.warning(f"刷流追新自定义 qBittorrent 连接失败：{err}")
            return None, f"自定义 qBittorrent 连接失败：{err}"

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
            if "uid" not in site and site.get("site_uid"):
                site["uid"] = site.get("site_uid")
            if "passkey" not in site and site.get("site_passkey"):
                site["passkey"] = site.get("site_passkey")
            for rule in site.get("rss_rules") or []:
                if "publish_age_to_minutes" not in rule and rule.get("max_age_minutes") is not None:
                    rule["publish_age_from_minutes"] = 0
                    rule["publish_age_to_minutes"] = rule.get("max_age_minutes")
                if "size_from_gib" not in rule and rule.get("min_size_gib") is not None:
                    rule["size_from_gib"] = rule.get("min_size_gib")
                    rule["size_to_gib"] = None
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
            task_names = [rule["name"] for rule in site["rss_rules"]]
            for rule in site["cleanup_rules"]:
                labels = [label for label in split_terms(rule.get("labels")) if label in task_names]
                rule["labels"] = labels or list(task_names)
        return data

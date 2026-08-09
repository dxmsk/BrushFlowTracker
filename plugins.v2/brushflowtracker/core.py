"""刷流追新的无副作用规则与数据标准化函数。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


RESOLUTION_RANK = {
    "other": 0,
    "480p": 1,
    "576p": 1,
    "720p": 2,
    "1080i": 3,
    "1080p": 4,
    "2160p": 5,
    "4k": 5,
    "8k": 6,
}

RESOLUTION_PATTERNS = (
    ("8K", re.compile(r"(?<!\d)(?:8K|4320P)(?!\d)", re.I)),
    ("4K", re.compile(r"(?<!\d)(?:4K|UHD|2160[PI])(?!\d)", re.I)),
    ("1080P", re.compile(r"(?<!\d)1080P(?!\d)", re.I)),
    ("1080I", re.compile(r"(?<!\d)1080I(?!\d)", re.I)),
    ("720P", re.compile(r"(?<!\d)720P(?!\d)", re.I)),
    ("576P", re.compile(r"(?<!\d)576P(?!\d)", re.I)),
    ("480P", re.compile(r"(?<!\d)480P(?!\d)", re.I)),
)

FREE_MARKER = re.compile(r"(?:^|[\s\[【(])(?:FREE|免费)(?:$|[\s\]】)])", re.I)
TWO_X_MARKER = re.compile(r"(?:2\s*[xX倍].*?(?:FREE|免费)|(?:FREE|免费).*?2\s*[xX倍])", re.I)
FREE_UNTIL_PATTERNS = (
    re.compile(
        r"(?:free\s*(?:until|ends?)|免费(?:截止|结束|到期)(?:时间)?)[\s:：-]*"
        r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?)",
        re.I,
    ),
    re.compile(
        r"(?:free\s*(?:until|ends?)|免费(?:截止|结束|到期)(?:时间)?)[\s:：-]*"
        r"(\d{1,2}[-/.]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?)",
        re.I,
    ),
)
FREE_REMAINING = re.compile(
    r"(?:free\s*(?:left|remaining)|免费剩余)[\s:：-]*"
    r"(?:(\d+)\s*(?:天|d(?:ays?)?))?\s*"
    r"(?:(\d+)\s*(?:小时|h(?:ours?)?))?\s*"
    r"(?:(\d+)\s*(?:分钟|m(?:in(?:utes?)?)?))?",
    re.I,
)


def split_terms(value: Any) -> List[str]:
    """将数组或逗号、换行分隔文本标准化为非空字符串列表。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[,，\n]", str(value))
    return [str(item).strip() for item in values if str(item).strip()]


def parse_datetime(value: Any, now: Optional[datetime] = None) -> Optional[datetime]:
    """把常见 RSS 日期、时间戳或 ISO 文本解析为带时区时间。"""
    if value in (None, ""):
        return None
    reference = now or datetime.now().astimezone()
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, (int, float)) or str(value).strip().isdigit():
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        result = datetime.fromtimestamp(number, tz=reference.tzinfo)
    else:
        text = str(value).strip()
        result = None
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                result = parsedate_to_datetime(text)
            except (TypeError, ValueError, OverflowError):
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        result = datetime.strptime(text, fmt)
                        break
                    except ValueError:
                        continue
        if result is None:
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=reference.tzinfo or timezone.utc)
    return result.astimezone(reference.tzinfo or timezone.utc)


def detect_resolution(title: str) -> Tuple[str, int]:
    """识别标题分辨率并返回展示值与排序等级。"""
    for label, pattern in RESOLUTION_PATTERNS:
        if pattern.search(title or ""):
            return label, RESOLUTION_RANK[label.lower()]
    return "OTHER", RESOLUTION_RANK["other"]


def media_key(title: str) -> str:
    """生成跨分辨率稳定的影视身份键，用于持久化最高画质去重。"""
    text = (title or "").upper()
    text = re.sub(
        r"\b(?:8K|4K|UHD|2160[PI]|1080[PI]|720P|576P|480P|"
        r"BLU-?RAY|REMUX|WEB-?DL|WEBRIP|HDTV|BDRIP|DVDRIP|"
        r"X26[45]|H26[45]|HEVC|AVC|HDR10\+?|HDR|DV|DOLBY\s*VISION|"
        r"AAC|DTS(?:-HD)?|TRUEHD|ATMOS)\b",
        " ",
        text,
    )
    text = re.sub(r"\b(?:PROPER|REPACK|EXTENDED|UNCUT|MULTI|CHS|CHT)\b", " ", text)
    text = re.sub(r"[._\-\[\](){}【】]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        text = title.strip().upper()
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:24]


def promotion_of(item: Dict[str, Any]) -> str:
    """识别普通、免费和双倍上传免费促销。"""
    download_factor = _number(item.get("downloadvolumefactor"), None)
    upload_factor = _number(item.get("uploadvolumefactor"), None)
    text = " ".join(str(item.get(key) or "") for key in ("title", "description", "promotion", "volume_factor"))
    is_free = download_factor == 0 or bool(FREE_MARKER.search(text))
    is_two_x = (upload_factor is not None and upload_factor >= 2) or bool(TWO_X_MARKER.search(text))
    if is_free and is_two_x:
        return "2xfree"
    if is_free:
        return "free"
    return "normal"


def free_until_of(item: Dict[str, Any], now: Optional[datetime] = None) -> Optional[datetime]:
    """从结构化字段或描述文本提取免费截止时间。"""
    reference = now or datetime.now().astimezone()
    for key in ("freedate", "free_until", "free_end", "promotion_end"):
        parsed = parse_datetime(item.get(key), reference)
        if parsed:
            return parsed
    text = " ".join(str(item.get(key) or "") for key in ("title", "description"))
    for pattern in FREE_UNTIL_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group(1).replace("/", "-").replace(".", "-")
        if re.match(r"^\d{1,2}-\d{1,2}", raw):
            raw = f"{reference.year}-{raw}"
        parsed = parse_datetime(raw, reference)
        if parsed and parsed < reference - timedelta(days=2):
            parsed = parsed.replace(year=parsed.year + 1)
        return parsed
    remaining = FREE_REMAINING.search(text)
    if remaining and any(remaining.groups()):
        days, hours, minutes = (int(value or 0) for value in remaining.groups())
        return reference + timedelta(days=days, hours=hours, minutes=minutes)
    return None


def normalize_item(raw: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """把 MoviePilot RSS 结果标准化为选种流程使用的字段。"""
    title = str(raw.get("title") or "").strip()
    resolution, rank = detect_resolution(title)
    pubdate = parse_datetime(raw.get("pubdate") or raw.get("published"), now)
    promotion = promotion_of(raw)
    free_until = free_until_of(raw, now) if promotion != "normal" else None
    enclosure = str(raw.get("enclosure") or raw.get("link") or "").strip()
    return {
        **raw,
        "title": title,
        "enclosure": enclosure,
        "size": int(_number(raw.get("size"), 0) or 0),
        "pubdate": pubdate,
        "resolution": resolution,
        "resolution_rank": rank,
        "media_key": media_key(title),
        "promotion": promotion,
        "free_until": free_until,
    }


def match_rule(item: Dict[str, Any], rule: Dict[str, Any], now: Optional[datetime] = None) -> Tuple[bool, str]:
    """判断标准化 RSS 条目是否满足一条选种规则。"""
    if not item.get("title") or not item.get("enclosure"):
        return False, "条目缺少标题或下载地址"
    haystack = f"{item.get('title', '')}\n{item.get('description', '')}".casefold()
    required = split_terms(rule.get("required_keywords"))
    excluded = split_terms(rule.get("excluded_keywords"))
    if required and not all(term.casefold() in haystack for term in required):
        return False, "缺少必须关键词"
    if excluded and any(term.casefold() in haystack for term in excluded):
        return False, "命中排除关键词"
    resolutions = {str(value).upper() for value in rule.get("resolutions") or []}
    if resolutions and item.get("resolution") not in resolutions:
        return False, "分辨率不匹配"
    min_bytes = float(rule.get("min_size_gib") or 0) * 1024 ** 3
    if min_bytes and int(item.get("size") or 0) < min_bytes:
        return False, "文件小于最小限制"
    max_age = float(rule.get("max_age_minutes") or 0)
    pubdate = item.get("pubdate")
    reference = now or datetime.now().astimezone()
    if max_age and (not pubdate or reference - pubdate > timedelta(minutes=max_age)):
        return False, "超过发种时间限制"
    promotion_filter = rule.get("promotion", "any")
    if promotion_filter == "free" and item.get("promotion") != "free":
        return False, "不是免费种"
    if promotion_filter == "free_or_2xfree" and item.get("promotion") not in {"free", "2xfree"}:
        return False, "不在免费促销期"
    if promotion_filter == "2xfree" and item.get("promotion") != "2xfree":
        return False, "不是双倍上传免费种"
    return True, "命中"


def choose_highest(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同一批候选中仅保留每个影视身份的最高分辨率条目。"""
    chosen: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for item in items:
        key = str(item.get("media_key") or media_key(str(item.get("title") or "")))
        if key not in chosen:
            chosen[key] = item
            order.append(key)
        elif int(item.get("resolution_rank") or 0) > int(chosen[key].get("resolution_rank") or 0):
            chosen[key] = item
    return [chosen[key] for key in order]


def dedup_allows(item: Dict[str, Any], records: Dict[str, Dict[str, Any]]) -> bool:
    """判断持久化记录是否允许下载当前最高画质候选。"""
    record = records.get(str(item.get("media_key") or ""))
    if not record:
        return True
    return int(item.get("resolution_rank") or 0) > int(record.get("resolution_rank") or 0)


def torrent_tags(torrent: Dict[str, Any]) -> List[str]:
    """将 qBittorrent 标签字段标准化为列表。"""
    return split_terms(torrent.get("tags"))


def first_cleanup_rule(
    torrent: Dict[str, Any], rules: Iterable[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """按配置顺序返回首条同时满足标签和阈值的删种规则。"""
    tags = set(torrent_tags(torrent))
    ratio = float(_number(torrent.get("ratio"), 0) or 0)
    seeding_time = float(_number(torrent.get("seeding_time"), 0) or 0)
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        required_tags = set(split_terms(rule.get("labels")))
        if required_tags and not required_tags.issubset(tags):
            continue
        if seeding_time < float(rule.get("min_seed_hours") or 0) * 3600:
            continue
        if ratio < float(rule.get("min_ratio") or 0):
            continue
        return rule
    return None


def isoformat(value: Optional[datetime]) -> Optional[str]:
    """将可选时间转换为稳定的 ISO 8601 文本。"""
    return value.isoformat() if value else None


def _number(value: Any, default: Optional[float]) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

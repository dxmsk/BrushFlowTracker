"""刷流追新插件的 API 请求模型。"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RssRulePayload(BaseModel):
    """单条 RSS 选种规则。"""

    id: str = ""
    name: str = "RSS 规则"
    enabled: bool = True
    url: str = ""
    required_keywords: List[str] = Field(default_factory=list)
    excluded_keywords: List[str] = Field(default_factory=list)
    resolutions: List[str] = Field(default_factory=list)
    max_age_minutes: Optional[float] = Field(default=None, ge=0)
    min_size_gib: Optional[float] = Field(default=None, ge=0)
    promotion: Literal["any", "free", "free_or_2xfree", "2xfree"] = "any"
    tags: List[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """限制订阅地址为 HTTP(S)，避免意外读取本地协议。"""
        cleaned = value.strip()
        if cleaned and not cleaned.lower().startswith(("http://", "https://")):
            raise ValueError("RSS 地址必须使用 http:// 或 https://")
        return cleaned


class CleanupRulePayload(BaseModel):
    """按顺序匹配的自动删种规则。"""

    id: str = ""
    name: str = "删种规则"
    enabled: bool = True
    labels: List[str] = Field(default_factory=list)
    min_seed_hours: float = Field(default=0, ge=0)
    min_ratio: float = Field(default=0, ge=0)
    delete_files: bool = False


class SitePayload(BaseModel):
    """一个逻辑站点及其 RSS、删种规则。"""

    id: str = ""
    name: str = "新站点"
    enabled: bool = True
    use_proxy: bool = False
    user_agent: str = ""
    rss_rules: List[RssRulePayload] = Field(default_factory=list)
    cleanup_rules: List[CleanupRulePayload] = Field(default_factory=list)


class SettingsPayload(BaseModel):
    """插件全局设置和站点集合。"""

    enabled: bool = False
    show_sidebar_nav: bool = True
    downloader: str = ""
    highest_resolution_dedup: bool = True
    rss_interval_minutes: int = Field(default=10, ge=1, le=10080)
    free_monitor_interval_minutes: int = Field(default=2, ge=1, le=1440)
    cleanup_interval_minutes: int = Field(default=30, ge=1, le=10080)
    request_timeout_seconds: int = Field(default=20, ge=5, le=120)
    history_limit: int = Field(default=500, ge=50, le=5000)
    sites: List[SitePayload] = Field(default_factory=list)


class RunPayload(BaseModel):
    """立即执行后台操作的请求。"""

    operation: Literal["rss", "free_monitor", "cleanup"]
    site_id: Optional[str] = None


class DownloaderTestPayload(BaseModel):
    """测试一个 qBittorrent 服务的请求。"""

    downloader: str = ""

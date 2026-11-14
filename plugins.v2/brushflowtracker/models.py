"""刷流追新插件的 API 请求模型。"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class RssRulePayload(BaseModel):
    """单个可自定义名称的 RSS 选种任务。"""

    id: str = ""
    name: str = "RSS 任务"
    enabled: bool = True
    url: str = ""
    # 每条任务可使用独立的站点身份；为空时回退到站点级默认值。
    uid: str = ""
    passkey: str = ""
    rss_key: str = ""
    rss_key_name: str = "rsskey"
    cookie: str = ""
    user_agent: str = ""
    referer: str = ""
    use_proxy: Optional[bool] = None
    whitelist_keywords: List[str] = Field(default_factory=list)
    blacklist_keywords: List[str] = Field(default_factory=list)
    resolutions: List[str] = Field(default_factory=list)
    publish_age_from_value: Optional[float] = Field(default=None, ge=0)
    publish_age_from_unit: Literal["seconds", "minutes", "hours", "days"] = "minutes"
    publish_age_to_value: Optional[float] = Field(default=None, ge=0)
    publish_age_to_unit: Literal["seconds", "minutes", "hours", "days"] = "minutes"
    size_from_value: Optional[float] = Field(default=None, ge=0)
    size_from_unit: Literal["kib", "mib", "gib", "tib"] = "gib"
    size_to_value: Optional[float] = Field(default=None, ge=0)
    size_to_unit: Literal["kib", "mib", "gib", "tib"] = "gib"
    promotion: Literal["any", "free", "free_or_2xfree", "2xfree"] = "any"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """保证任务名可直接作为一个完整的 qBittorrent 标签。"""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("任务名称不能为空")
        if "," in cleaned:
            raise ValueError("任务名称不能包含英文逗号")
        return cleaned

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        """限制订阅地址为 HTTP(S)，避免意外读取本地协议。"""
        cleaned = value.strip()
        if cleaned and not cleaned.lower().startswith(("http://", "https://")):
            raise ValueError("RSS 地址必须使用 http:// 或 https://")
        return cleaned

    @model_validator(mode="after")
    def validate_ranges(self) -> "RssRulePayload":
        """保证发种时间和文件大小范围的起点不大于终点。"""
        age_factors = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}
        size_factors = {"kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}
        if (
            self.publish_age_from_value is not None
            and self.publish_age_to_value is not None
            and self.publish_age_from_value * age_factors[self.publish_age_from_unit]
            > self.publish_age_to_value * age_factors[self.publish_age_to_unit]
        ):
            raise ValueError("发种时间范围起点不能大于终点")
        if (
            self.size_from_value is not None
            and self.size_to_value is not None
            and self.size_from_value * size_factors[self.size_from_unit]
            > self.size_to_value * size_factors[self.size_to_unit]
        ):
            raise ValueError("文件大小范围起点不能大于终点")
        return self


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
    # NexusPHP/Tracker 站点身份信息。配置后会自动补到 RSS/详情请求，
    # 既方便使用不带身份参数的 RSS 地址，也能降低站点返回 403 的概率。
    uid: str = ""
    passkey: str = ""
    rss_rules: List[RssRulePayload] = Field(default_factory=list)
    cleanup_rules: List[CleanupRulePayload] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """保证站点名称与任务名称一样可明确编辑且不能为空。"""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("站点名称不能为空")
        return cleaned


class SettingsPayload(BaseModel):
    """插件全局设置和站点集合。"""

    enabled: bool = False
    show_sidebar_nav: bool = True
    # moviepilot 使用 MoviePilot 下载器管理中已配置的 qB；custom 使用下面的直连参数。
    downloader_mode: Literal["moviepilot", "custom"] = "moviepilot"
    downloader: str = ""
    custom_qb_url: str = ""
    custom_qb_host: str = ""
    custom_qb_port: int = Field(default=8080, ge=1, le=65535)
    custom_qb_username: str = ""
    custom_qb_password: str = ""
    custom_qb_save_path: str = ""
    highest_resolution_dedup: bool = True
    avoid_dead_seeds: bool = True
    dead_seed_wait_minutes: int = Field(default=30, ge=1, le=10080)
    dead_seed_min_seeders: int = Field(default=1, ge=0, le=1000)
    dead_seed_delete_files: bool = True
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
    downloader_mode: Literal["moviepilot", "custom"] = "moviepilot"
    custom_qb_url: str = ""
    custom_qb_host: str = ""
    custom_qb_port: int = Field(default=8080, ge=1, le=65535)
    custom_qb_username: str = ""
    custom_qb_password: str = ""
    custom_qb_save_path: str = ""

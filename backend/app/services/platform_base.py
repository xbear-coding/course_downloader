"""平台插件抽象基类"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


@dataclass
class LoginResult:
    success: bool
    error_code: Optional[str] = None  # TIMEOUT / INVALID_CREDENTIALS / CAPTCHA_REQUIRED
    error_message: Optional[str] = None


@dataclass
class ContentItem:
    platform: str
    item_id: str
    title: str
    content_type: str  # video / article / note
    url: str
    metadata: dict = field(default_factory=dict)


@dataclass
class FetchResult:
    items: list[ContentItem]
    next_token: Optional[str] = None  # 分页游标
    total_estimated: Optional[int] = None
    partial: bool = False  # 是否部分加载成功


@dataclass
class DownloadResult:
    success: bool
    file_path: Optional[Path] = None
    file_type: str = ""
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    raw_path: Optional[Path] = None  # 转码失败时保留源文件


class BasePlatform(ABC):
    """所有平台必须实现的核心接口"""

    @abstractmethod
    async def login(self, account_id: int) -> LoginResult:
        ...

    @abstractmethod
    async def fetch_list(self, page_token: Optional[str] = None) -> FetchResult:
        ...

    @abstractmethod
    async def get_metadata(self, item: ContentItem) -> dict:
        ...


class VideoCapable(ABC):
    """支持视频下载的平台"""

    @abstractmethod
    async def download_video(
        self, item: ContentItem, output: Path, quality: str = "720p"
    ) -> DownloadResult:
        ...


class ArticleCapable(ABC):
    """支持文章抓取的平台"""

    @abstractmethod
    async def download_article(self, item: ContentItem, output: Path) -> DownloadResult:
        ...


class SubtitleCapable(ABC):
    """支持字幕下载的平台"""

    @abstractmethod
    async def download_subtitle(self, item: ContentItem, language: str = "zh") -> str:
        ...

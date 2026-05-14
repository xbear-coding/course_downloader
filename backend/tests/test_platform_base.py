"""测试 platform_base 数据类和抽象基类"""
import pytest
from pathlib import Path
from app.services.platform_base import (
    LoginResult, ContentItem, FetchResult, DownloadResult,
    BasePlatform, VideoCapable, ArticleCapable, SubtitleCapable,
)


class TestLoginResult:
    """LoginResult 数据类"""

    def test_success_default(self):
        r = LoginResult(success=True)
        assert r.success is True
        assert r.error_code is None
        assert r.error_message is None

    def test_failure_with_details(self):
        r = LoginResult(success=False, error_code="TIMEOUT", error_message="扫码超时")
        assert r.success is False
        assert r.error_code == "TIMEOUT"
        assert r.error_message == "扫码超时"

    def test_failure_minimal(self):
        r = LoginResult(success=False)
        assert r.success is False
        assert r.error_code is None

    def test_error_code_enum_values(self):
        """验证所有标准错误码都能被赋值"""
        for code in ("TIMEOUT", "INVALID_CREDENTIALS", "CAPTCHA_REQUIRED"):
            r = LoginResult(success=False, error_code=code)
            assert r.error_code == code


class TestContentItem:
    """ContentItem 数据类"""

    def test_minimal(self):
        item = ContentItem(
            platform="tencent_meeting",
            item_id="rec_001",
            title="测试录制",
            content_type="video",
            url="https://example.com/video",
        )
        assert item.platform == "tencent_meeting"
        assert item.item_id == "rec_001"
        assert item.content_type == "video"
        assert item.metadata == {}

    def test_with_metadata(self):
        item = ContentItem(
            platform="bilibili",
            item_id="BV1xx",
            title="测试视频",
            content_type="video",
            url="https://bilibili.com/video/BV1xx",
            metadata={"duration": 120, "bvid": "BV1xx"},
        )
        assert item.metadata["duration"] == 120

    def test_article_type(self):
        item = ContentItem(
            platform="toutiao",
            item_id="art_001",
            title="测试文章",
            content_type="article",
            url="https://example.com/article",
        )
        assert item.content_type == "article"


class TestFetchResult:
    """FetchResult 数据类"""

    def test_empty(self):
        r = FetchResult(items=[])
        assert r.items == []
        assert r.next_token is None
        assert r.total_estimated is None
        assert r.partial is False

    def test_with_items_and_pagination(self):
        items = [
            ContentItem(
                platform="test", item_id="1", title="A",
                content_type="video", url="https://example.com/1",
            )
        ]
        r = FetchResult(items=items, next_token="2", total_estimated=10)
        assert len(r.items) == 1
        assert r.next_token == "2"
        assert r.total_estimated == 10

    def test_partial(self):
        r = FetchResult(items=[], partial=True)
        assert r.partial is True


class TestDownloadResult:
    """DownloadResult 数据类"""

    def test_success_with_path(self):
        r = DownloadResult(success=True, file_path=Path("/tmp/test.mp4"), file_type="mp4")
        assert r.success is True
        assert r.file_path == Path("/tmp/test.mp4")
        assert r.file_type == "mp4"

    def test_failure(self):
        r = DownloadResult(success=False, error_code="DOWNLOAD_FAILED", error_message="网络错误")
        assert r.success is False
        assert r.error_code == "DOWNLOAD_FAILED"

    def test_with_raw_path(self):
        r = DownloadResult(
            success=False,
            error_code="CONVERT_FAILED",
            raw_path=Path("/tmp/test.ts"),
        )
        assert r.raw_path == Path("/tmp/test.ts")


class TestAbstractBaseClasses:
    """抽象基类接口契约"""

    def test_base_platform_abstract(self):
        """验证 BasePlatform 不能直接实例化"""
        with pytest.raises(TypeError):
            BasePlatform()

    def test_video_capable_abstract(self):
        """验证 VideoCapable 不能直接实例化"""
        with pytest.raises(TypeError):
            VideoCapable()

    def test_article_capable_abstract(self):
        """验证 ArticleCapable 不能直接实例化"""
        with pytest.raises(TypeError):
            ArticleCapable()

    def test_subtitle_capable_abstract(self):
        """验证 SubtitleCapable 不能直接实例化"""
        with pytest.raises(TypeError):
            SubtitleCapable()


class TestConcretePluginContracts:
    """验证具体平台插件遵循接口契约"""

    def test_tencent_meeting_implements_base(self):
        from app.platforms.tencent_meeting import TencentMeetingPlugin
        p = TencentMeetingPlugin()
        assert isinstance(p, BasePlatform)
        assert hasattr(p, "login")
        assert hasattr(p, "fetch_list")
        assert hasattr(p, "get_metadata")

    def test_tencent_meeting_is_video_capable(self):
        from app.platforms.tencent_meeting import TencentMeetingPlugin
        from app.services.platform_base import VideoCapable
        p = TencentMeetingPlugin()
        assert isinstance(p, VideoCapable)
        assert hasattr(p, "download_video")

    def test_bilibili_implements_subtitle(self):
        from app.platforms.bilibili import BilibiliPlugin
        from app.services.platform_base import SubtitleCapable
        p = BilibiliPlugin()
        assert isinstance(p, SubtitleCapable)
        assert hasattr(p, "download_subtitle")

    def test_xiaohongshu_implements_article(self):
        from app.platforms.xiaohongshu import XiaohongshuPlugin
        from app.services.platform_base import ArticleCapable
        p = XiaohongshuPlugin()
        assert isinstance(p, ArticleCapable)
        assert hasattr(p, "download_article")

    def test_all_plugins_platform_property(self):
        """所有插件必须正确返回 platform 名称"""
        from app.platforms import list_platforms, get_platform
        platforms = list_platforms()
        assert "tencent_meeting" in platforms
        assert "xiaoe" in platforms
        assert "bilibili" in platforms
        assert "xiaohongshu" in platforms
        assert "toutiao" in platforms
        assert "douyin" in platforms

        for name in platforms:
            p = get_platform(name)
            assert p is not None
            assert p.platform == name

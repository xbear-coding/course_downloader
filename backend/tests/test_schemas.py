"""测试 Pydantic schemas 验证逻辑"""
import pytest
from pydantic import ValidationError
from app.schemas import (
    PlatformCreate, PlatformResponse,
    AccountCreate, AccountResponse,
    TaskCreate, TaskResponse,
    APIKeyCreate, APIKeyResponse,
    Pagination, PaginatedResponse, ErrorResponse,
)


class TestPlatformCreate:
    """平台创建请求验证"""

    def test_valid(self):
        data = PlatformCreate(name="tencent_meeting", display_name="腾讯会议")
        assert data.name == "tencent_meeting"
        assert data.display_name == "腾讯会议"
        assert data.output_dir is None

    def test_with_output_dir(self):
        data = PlatformCreate(name="xiaoe", display_name="小鹅通", output_dir="/data/output")
        assert data.output_dir == "/data/output"

    def test_name_pattern(self):
        """name 只允许小写字母和下划线"""
        with pytest.raises(ValidationError):
            PlatformCreate(name="Tencent Meeting", display_name="腾讯会议")

    def test_name_valid_pattern(self):
        """带下划线的 name 应该通过"""
        data = PlatformCreate(name="tencent_meeting", display_name="腾讯会议")
        assert data.name == "tencent_meeting"

    def test_empty_display_name(self):
        with pytest.raises(ValidationError):
            PlatformCreate(name="test", display_name="")

    def test_display_name_too_long(self):
        with pytest.raises(ValidationError):
            PlatformCreate(name="test", display_name="A" * 51)


class TestAccountCreate:
    """账号创建请求验证"""

    def test_valid(self):
        data = AccountCreate(platform_id=1, name="熊子熠")
        assert data.platform_id == 1
        assert data.name == "熊子熠"

    def test_empty_name(self):
        with pytest.raises(ValidationError):
            AccountCreate(platform_id=1, name="")


class TestTaskCreate:
    """任务创建请求验证"""

    def test_valid_minimal(self):
        data = TaskCreate(platform="tencent_meeting", resource_id="rec_001", title="测试录制")
        assert data.platform == "tencent_meeting"
        assert data.resource_id == "rec_001"
        assert data.title == "测试录制"
        assert data.content_type == "video"
        assert data.url is None

    def test_valid_with_url(self):
        data = TaskCreate(
            platform="bilibili", resource_id="BV1xx",
            title="测试", content_type="video",
            url="https://bilibili.com/video/BV1xx",
        )
        assert data.url == "https://bilibili.com/video/BV1xx"

    def test_empty_resource_id(self):
        with pytest.raises(ValidationError):
            TaskCreate(platform="test", resource_id="", title="测试")

    def test_empty_title(self):
        with pytest.raises(ValidationError):
            TaskCreate(platform="test", resource_id="abc", title="")

    def test_article_content_type(self):
        data = TaskCreate(platform="toutiao", resource_id="art_001", title="文章", content_type="article")
        assert data.content_type == "article"


class TestAPIKeyCreate:
    """API Key 创建请求验证"""

    def test_valid(self):
        data = APIKeyCreate(name="SiliconFlow Key", key_value="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        assert data.name == "SiliconFlow Key"
        assert data.key_value.startswith("sk-")
        assert data.provider == "siliconflow"

    def test_custom_provider(self):
        data = APIKeyCreate(name="Groq Key", key_value="gsk-xxxxxxxxxxxx", provider="groq")
        assert data.provider == "groq"

    def test_key_too_short(self):
        with pytest.raises(ValidationError):
            APIKeyCreate(name="test", key_value="short")

    def test_empty_name(self):
        with pytest.raises(ValidationError):
            APIKeyCreate(name="", key_value="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")


class TestResponseModels:
    """响应模型 from_attributes 支持"""

    def test_platform_response_config(self):
        assert PlatformResponse.model_config is not None

    def test_account_response_config(self):
        assert AccountResponse.model_config is not None

    def test_task_response_optional_fields(self):
        """验证可选字段默认值为 None"""
        from datetime import datetime
        # 模拟 ORM 对象
        mock_task = type('MockTask', (), {
            'id': 1,
            'platform': 'test',
            'resource_id': 'abc',
            'title': '测试',
            'content_type': 'video',
            'status': 'pending',
            'video_path': None,
            'transcript_path': None,
            'error_message': None,
            'retry_count': 0,
            'created_at': datetime.now(),
            'downloaded_at': None,
        })()

        response = TaskResponse.model_validate(mock_task)
        assert response.id == 1
        assert response.video_path is None
        assert response.transcript_path is None
        assert response.error_message is None
        assert response.downloaded_at is None


class TestPagination:
    """分页模型"""

    def test_valid(self):
        p = Pagination(page=1, page_size=20, total_items=100, total_pages=5)
        assert p.page == 1
        assert p.total_pages == 5

    def test_zero_items(self):
        p = Pagination(page=1, page_size=20, total_items=0, total_pages=0)
        assert p.total_items == 0
        assert p.total_pages == 0

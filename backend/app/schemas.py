"""
Course_Downloader — Pydantic 请求/响应模型
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime


# ── 平台 ──

class PlatformCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z_]+$")
    display_name: str = Field(min_length=1, max_length=50)
    output_dir: Optional[str] = None


class PlatformResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    display_name: str
    enabled: bool
    output_dir: Optional[str]
    sort_order: int
    created_at: datetime


# ── 账号 ──

class AccountCreate(BaseModel):
    platform_id: int
    name: str = Field(min_length=1, max_length=100)


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    platform_id: int
    name: str
    is_active: bool
    last_login: Optional[datetime]


# ── 任务 ──

class TaskCreate(BaseModel):
    platform: str
    resource_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)
    content_type: str = "video"
    url: Optional[str] = None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    platform: str
    resource_id: Optional[str]
    title: str
    content_type: str
    status: str
    video_path: Optional[str]
    transcript_path: Optional[str]
    error_message: Optional[str]
    retry_count: int
    created_at: datetime
    downloaded_at: Optional[datetime]


# ── API Key ──

class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1)
    key_value: str = Field(min_length=10)
    provider: str = "siliconflow"


class APIKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    key_value: str  # 前端应只显示后 4 位
    provider: str
    is_active: bool


# ── 通用 ──

class ErrorResponse(BaseModel):
    code: str
    message: str
    detail: Optional[dict] = None


class Pagination(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class PaginatedResponse(BaseModel):
    data: list
    pagination: Pagination

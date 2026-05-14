"""
Course_Downloader — SQLAlchemy ORM 模型
"""
import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime,
    ForeignKey, Text, Enum, Index, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    FATAL = "fatal"
    UPDATED = "updated"
    NEW = "new"


class StepStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class Platform(Base):
    __tablename__ = "platforms"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)
    display_name = Column(String(50), nullable=False)
    enabled = Column(Boolean, default=True)
    output_dir = Column(String(500))
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    accounts = relationship("Account", back_populates="platform", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    platform_id = Column(Integer, ForeignKey("platforms.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    cookie_file = Column(String(200))
    is_active = Column(Boolean, default=False)
    last_login = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    platform = relationship("Platform", back_populates="accounts")
    tasks = relationship("Task", back_populates="account")

    __table_args__ = (UniqueConstraint("platform_id", "name"),)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="SET NULL"))
    platform = Column(String(50), nullable=False)
    resource_id = Column(String(200))
    title = Column(String(500))
    content_type = Column(String(20), default="video")
    url = Column(String(500))
    status = Column(Enum(TaskStatus), default=TaskStatus.PENDING)

    # 子步骤独立状态
    video_status = Column(Enum(StepStatus), default=StepStatus.PENDING)
    subtitle_status = Column(Enum(StepStatus), default=StepStatus.PENDING)
    transcript_status = Column(Enum(StepStatus), default=StepStatus.PENDING)
    article_status = Column(Enum(StepStatus), default=StepStatus.PENDING)

    # 输出文件路径
    video_path = Column(String(500))
    subtitle_path = Column(String(500))
    transcript_path = Column(String(500))
    article_path = Column(String(500))

    # 错误与重试
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)

    # 元数据（用于增量检测）
    duration_seconds = Column(Integer)
    file_size_bytes = Column(Integer)
    server_updated_at = Column(DateTime)
    file_hash = Column(String(64))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    downloaded_at = Column(DateTime)

    account = relationship("Account", back_populates="tasks")

    __table_args__ = (
        UniqueConstraint("platform", "resource_id"),
        Index("idx_tasks_status", "status"),
        Index("idx_tasks_platform", "platform"),
        Index("idx_tasks_platform_status", "platform", "status"),
    )


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    key_value = Column(String(500), nullable=False)
    provider = Column(String(50))
    is_active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

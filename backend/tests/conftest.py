"""测试基础设施 — 共享 Fixtures"""
import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import get_db
from app.models import Base
from app.main import app

# 使用内存数据库，每个测试函数独立
TEST_DB_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def db_session():
    """每个测试函数独立的数据库会话"""
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session):
    """FastAPI 测试客户端（注入内存 DB）"""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_db(db_session):
    """预先填充种子数据的数据库"""
    from app.models import Platform

    platforms = [
        Platform(name="tencent_meeting", display_name="腾讯会议", sort_order=1, enabled=True),
        Platform(name="xiaoe", display_name="小鹅通", sort_order=2, enabled=True),
        Platform(name="bilibili", display_name="B站", sort_order=3, enabled=True),
        Platform(name="xiaohongshu", display_name="小红书", sort_order=4, enabled=True),
        Platform(name="toutiao", display_name="今日头条", sort_order=5, enabled=True),
        Platform(name="douyin", display_name="抖音", sort_order=6, enabled=True),
    ]
    for p in platforms:
        db_session.add(p)
    await db_session.commit()
    return db_session


@pytest_asyncio.fixture
async def seeded_client(seeded_db):
    """预填充种子数据的测试客户端"""
    from app.database import get_db

    async def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()

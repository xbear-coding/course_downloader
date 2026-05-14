"""
Course_Downloader — FastAPI 应用入口
"""
import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from app.api import platforms, tasks, keys, ws
from app.services.task_scheduler import TaskScheduler
from app.database import async_session, engine
from app.models import Base

logger = logging.getLogger(__name__)
load_dotenv()

scheduler = TaskScheduler()


async def seed_platforms():
    """首次启动时填充默认平台数据"""
    from app.models import Platform
    async with async_session() as db:
        from sqlalchemy import select, func
        count = (await db.execute(select(func.count()).select_from(Platform))).scalar()
        if count and count > 0:
            return

        defaults = [
            Platform(name="tencent_meeting", display_name="腾讯会议", sort_order=1, enabled=True),
            Platform(name="xiaoe", display_name="小鹅通", sort_order=2, enabled=True),
            Platform(name="bilibili", display_name="B站", sort_order=3, enabled=True),
            Platform(name="xiaohongshu", display_name="小红书", sort_order=4, enabled=True),
            Platform(name="toutiao", display_name="今日头条", sort_order=5, enabled=True),
            Platform(name="douyin", display_name="抖音", sort_order=6, enabled=True),
        ]
        for p in defaults:
            db.add(p)
        await db.commit()
        logger.info("已初始化 6 个默认平台")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_platforms()
    asyncio.create_task(scheduler.start())
    logger.info("Course_Downloader 已启动")
    yield
    # 关闭时
    await scheduler.stop()


app = FastAPI(
    title="Course_Downloader",
    version="0.1.0",
    description="多平台内容离线下载工具 API",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"未捕获异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误"}},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

# 注册路由
app.include_router(platforms.router)
app.include_router(tasks.router)
app.include_router(keys.router)
app.include_router(ws.router)

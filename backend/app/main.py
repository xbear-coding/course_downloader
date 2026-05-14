"""
Course_Downloader — FastAPI 应用入口
"""
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from app.api import platforms, tasks, keys, ws

load_dotenv()

app = FastAPI(
    title="Course_Downloader",
    version="0.1.0",
    description="多平台内容离线下载工具 API",
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

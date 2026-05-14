"""
Course_Downloader — 配置管理
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# 路径
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 数据库
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite+aiosqlite:///{DATA_DIR / 'course_downloader.db'}",
)

# 服务器
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

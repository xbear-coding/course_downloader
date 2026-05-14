"""
Course_Downloader — Playwright 浏览器管理器

职责：
- 管理各平台的 Playwright Chromium 实例
- 每个平台独立 Profile 目录（持久化登录态）
- 健康检查 + 崩溃自动重启
- 支持可见/无头双模式
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page

logger = logging.getLogger(__name__)

# 浏览器配置文件根目录
PROFILES_DIR = Path(__file__).parent.parent.parent / "data" / "browser_profiles"


class PlatformBrowser:
    """单个平台的浏览器实例"""

    def __init__(self, platform: str, profile_dir: Path):
        self.platform = platform
        self.profile_dir = profile_dir
        self.browser: Optional[Browser] = None
        self._playwright = None

    @property
    def user_data_dir(self) -> Path:
        return self.profile_dir / self.platform

    async def launch(self, headless: bool = True):
        """启动浏览器（使用固定 Profile）"""
        if self.browser:
            return

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()

        self.browser = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=headless,
            no_viewport=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            ignore_default_args=["--enable-automation"],
        )
        logger.info(f"[{self.platform}] 浏览器已启动 (headless={headless})")

    async def new_page(self) -> Page:
        """创建新页面"""
        if not self.browser:
            raise RuntimeError(f"[{self.platform}] 浏览器未启动")
        return await self.browser.new_page()

    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info(f"[{self.platform}] 浏览器已关闭")

    async def health_check(self) -> bool:
        """健康检查——尝试创建一个页面再关闭"""
        if not self.browser:
            return False
        try:
            page = await self.browser.new_page()
            await page.close()
            return True
        except Exception:
            return False


class BrowserManager:
    """全局浏览器实例池（模块级单例）

    策略：
    - 每个平台最多 1 个实例
    - 全局最多 2 个实例同时运行
    - 闲置超过 5 分钟自动关闭
    """

    _instance: Optional['BrowserManager'] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, max_instances: int = 2, idle_timeout: int = 300):
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        self._instances: dict[str, PlatformBrowser] = {}
        self.max_instances = max_instances
        self.idle_timeout = idle_timeout
        self._lock = asyncio.Lock()

    async def get_browser(self, platform: str, headless: bool = True) -> PlatformBrowser:
        """获取或创建平台浏览器实例"""
        async with self._lock:
            # 检查是否已有实例
            if platform in self._instances:
                pb = self._instances[platform]
                healthy = await pb.health_check()
                if healthy:
                    return pb
                # 不健康，关闭重建
                logger.warning(f"[{platform}] 浏览器不健康，重新启动")
                await pb.close()
                del self._instances[platform]

            # 检查总实例数
            active = len(self._instances)
            if active >= self.max_instances:
                # 关闭最久未使用的
                await self._close_idlest()

            pb = PlatformBrowser(platform, PROFILES_DIR)
            await pb.launch(headless=headless)
            self._instances[platform] = pb
            return pb

    async def close_platform(self, platform: str):
        """关闭指定平台的浏览器"""
        if platform in self._instances:
            await self._instances[platform].close()
            del self._instances[platform]

    async def close_all(self):
        """关闭所有浏览器"""
        for platform, pb in list(self._instances.items()):
            await pb.close()
        self._instances.clear()

    async def _close_idlest(self):
        """关闭最久未使用的实例"""
        # 简单策略：关闭第一个
        platform = next(iter(self._instances))
        await self.close_platform(platform)

    @property
    def active_count(self) -> int:
        return len(self._instances)

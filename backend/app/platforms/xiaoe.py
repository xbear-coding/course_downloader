"""小鹅通平台插件（appid 自动发现）"""
import asyncio
import logging
import re
from pathlib import Path
from typing import Optional, Pattern
from app.services.platform_base import (
    BasePlatform, VideoCapable,
    LoginResult, ContentItem, FetchResult, DownloadResult,
)
from app.services.browser_manager import BrowserManager
from app.database import async_session

logger = logging.getLogger(__name__)

# 小鹅通 appid 模式：app + 字母数字，约 15-24 位
APPID_PATTERN: Pattern = re.compile(r"app[a-zA-Z0-9]{14,24}")
# 通用入口
XIAOE_HOME = "https://www.xiaoe-tech.com"


def _extract_appid(url: str) -> str | None:
    """从 URL 中提取小鹅通 appid"""
    m = APPID_PATTERN.search(url)
    return m.group(0) if m else None


def _build_url(base_url: str, path: str = "") -> str:
    """构建 appid 对应的 URL（base_url 为完整基础 URL）"""
    return f"{base_url}{path}"


async def _get_account_appid(account_id: int) -> str | None:
    """从账号记录读取已保存的 appid（存储在 cookie_file 字段）"""
    from app.models import Account
    from sqlalchemy import select
    async with async_session() as db:
        acct = await db.get(Account, account_id)
        if acct and acct.cookie_file and acct.cookie_file.startswith("xiaoe:"):
            return acct.cookie_file.split(":", 1)[1]
    return None


async def _save_account_base_url(account_id: int, base_url: str):
    """将完整基础 URL 保存到账号记录"""
    from app.models import Account
    async with async_session() as db:
        acct = await db.get(Account, account_id)
        if acct:
            acct.cookie_file = f"xiaoe:{base_url}"
            await db.commit()
            logger.info(f"[xiaoe] 基础URL已保存: {base_url}")


class XiaoEPlugin(BasePlatform, VideoCapable):
    """小鹅通插件（appid 自动发现）

    流程：
    1. 登录 → 自动检测 appid → 持久化
    2. 课程列表：访问课程页 → 处理懒加载
    3. 下载：CDP 拦截 m3u8 → 下载合并
    """

    def __init__(self):
        self.browser_mgr = BrowserManager()
        self._appid: str | None = None

    @property
    def platform(self) -> str:
        return "xiaoe"

    async def _resolve_appid(self, account_id: int) -> str | None:
        """获取 appid：优先内存缓存 → 数据库 → None"""
        if self._appid:
            return self._appid
        self._appid = await _get_account_appid(account_id)
        return self._appid

    async def _check_logged_in(self, page) -> bool:
        """多维度检测是否已登录小鹅通"""
        url = page.url
        if "login" not in url.lower() and "www.xiaoe-tech.com" not in url:
            return True
        try:
            body = await page.inner_text("body")
            if "退出" in body or "我的课程" in body or "我的学习" in body:
                return True
            user_els = await page.query_selector_all(
                '[class*=avatar], [class*=user], [class*=User], '
                '[class*=userInfo], [class*=nickname]'
            )
            if user_els:
                return True
        except Exception:
            pass
        return False

    async def login(self, account_id: int) -> LoginResult:
        try:
            existing_base = await self._resolve_appid(account_id)
            start_url = (
                _build_url(existing_base, "/login")
                if existing_base
                else f"{XIAOE_HOME}/login"
            )

            pb = await self.browser_mgr.get_browser(self.platform, headless=False)
            page = await pb.new_page()
            await page.goto(start_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            if await self._check_logged_in(page):
                # 从当前 URL 提取基础地址并保存
                base = await page.evaluate("window.location.origin")
                if base and base != existing_base:
                    await _save_account_base_url(account_id, base)
                    self._appid = base
                return LoginResult(success=True)

            for _ in range(180):
                await asyncio.sleep(1)
                if await self._check_logged_in(page):
                    base = await page.evaluate("window.location.origin")
                    if base:
                        await _save_account_base_url(account_id, base)
                        self._appid = base
                    return LoginResult(success=True)

            return LoginResult(
                success=False, error_code="TIMEOUT",
                error_message="登录超时",
            )
        except Exception as e:
            return LoginResult(
                success=False, error_code="ERROR",
                error_message=str(e)[:100],
            )

    async def fetch_list(self, page_token: Optional[str] = None) -> FetchResult:
        # 需要 account_id 才能获取 appid，但 fetch_list 不传 account_id
        # 此处需要从 DB 获取当前活跃账号
        from app.models import Account, Platform
        from sqlalchemy import select

        async with async_session() as db:
            platform = (
                await db.execute(
                    select(Platform).where(Platform.name == "xiaoe")
                )
            ).scalar_one_or_none()
            if not platform:
                return FetchResult(items=[], partial=True)
            acct = (
                await db.execute(
                    select(Account).where(
                        Account.platform_id == platform.id,
                        Account.is_active == True,
                    )
                )
            ).scalar_one_or_none()
            if not acct:
                logger.warning("[xiaoe] 无活跃账号，无法获取列表")
                return FetchResult(items=[], partial=True)

            appid = await self._resolve_appid(acct.id)
            if not appid:
                appid = _extract_appid(acct.cookie_file or "")
            if not appid:
                logger.warning("[xiaoe] 未找到 appid，请先登录")
                return FetchResult(items=[], partial=True)

        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        try:
            list_url = _build_url(appid, "/course_list")
            await page.goto(list_url, wait_until="networkidle")
            await asyncio.sleep(3)

            items = []
            prev_count = -1
            stable_rounds = 0

            for _ in range(15):
                cards = await page.query_selector_all(
                    ".course-card, [class*='courseItem'], [class*='course-item'], "
                    ".course-list-item, .el-card, [class*='product']"
                )
                current_count = len(cards)
                if current_count == prev_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                prev_count = current_count
                if stable_rounds >= 3:
                    break
                await page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight)"
                )
                await asyncio.sleep(1.5)

            logger.info(f"[xiaoe] 检测到 {prev_count} 个课程卡片")

            for card in cards:
                try:
                    title_el = await card.query_selector(
                        ".title, [class*='title'], .name, [class*='name'], h3, h4"
                    )
                    title = (
                        await title_el.inner_text() if title_el else "未知课程"
                    )
                    title = title.strip()

                    link_el = await card.query_selector("a")
                    link = ""
                    if link_el:
                        link = await link_el.get_attribute("href") or ""

                    item_id = ""
                    if link:
                        m = re.search(r"/([a-zA-Z0-9]{20,})", link)
                        if m:
                            item_id = m.group(1)
                    if not item_id:
                        import hashlib
                        item_id = hashlib.md5(title.encode()).hexdigest()[:12]

                    items.append(
                        ContentItem(
                            platform="xiaoe",
                            item_id=item_id,
                            title=title,
                            content_type="video",
                            url=(
                                link
                                if link.startswith("http")
                                else _build_url(appid, link)
                            ),
                        )
                    )
                except Exception as e:
                    logger.warning(f"[xiaoe] 解析课程卡片失败: {e}")
                    continue

            return FetchResult(items=items, total_estimated=len(items))

        except Exception as e:
            logger.error(f"[xiaoe] 获取课程列表失败: {e}")
            return FetchResult(items=[], partial=True)
        finally:
            await page.close()

    async def download_video(
        self, item: ContentItem, output: Path, quality: str = "720p"
    ) -> DownloadResult:
        # 下载前尝试获取 appid
        from app.models import Account, Platform
        from sqlalchemy import select

        async with async_session() as db:
            platform = (
                await db.execute(
                    select(Platform).where(Platform.name == "xiaoe")
                )
            ).scalar_one_or_none()
            if platform:
                acct = (
                    await db.execute(
                        select(Account).where(
                            Account.platform_id == platform.id,
                            Account.is_active == True,
                        )
                    )
                ).scalar_one_or_none()
                if acct:
                    await self._resolve_appid(acct.id)

        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        m3u8_url = None

        async def intercept_response(response):
            nonlocal m3u8_url
            if response.url.endswith(".m3u8") and "xiaoe" in response.url:
                m3u8_url = response.url
                logger.info(f"[xiaoe] 拦截到 m3u8: {m3u8_url}")

        page.on("response", intercept_response)

        try:
            await page.goto(item.url, wait_until="networkidle")
            await asyncio.sleep(5)

            try:
                play_btn = await page.query_selector(
                    "button:has-text('播放'), .play-btn, [class*='play'], video"
                )
                if play_btn:
                    await play_btn.click()
                    await asyncio.sleep(3)
            except Exception:
                pass

            for _ in range(20):
                if m3u8_url:
                    break
                await asyncio.sleep(1)

            if m3u8_url:
                return await self._download_m3u8(m3u8_url, output)

            try:
                video_src = await page.evaluate(
                    """() => {
                    const v = document.querySelector('video');
                    return v ? (v.src || v.querySelector('source')?.src) : null;
                }"""
                )
                if video_src and video_src.startswith("http"):
                    import httpx
                    async with httpx.AsyncClient(timeout=300) as client:
                        resp = await client.get(video_src)
                        if resp.status_code == 200:
                            output.write_bytes(resp.content)
                            return DownloadResult(
                                success=True, file_path=output, file_type="ts"
                            )
            except Exception:
                pass

            return DownloadResult(
                success=False,
                error_code="NO_M3U8",
                error_message="未捕获到视频流",
            )
        except Exception as e:
            return DownloadResult(
                success=False, error_code="ERROR",
                error_message=str(e)[:200],
            )
        finally:
            page.remove_listener("response", intercept_response)
            await page.close()

    async def _download_m3u8(
        self, m3u8_url: str, output: Path
    ) -> DownloadResult:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(m3u8_url)
            if resp.status_code != 200:
                return DownloadResult(
                    success=False, error_code="M3U8_FETCH_FAIL"
                )

            m3u8_content = resp.text
            base_url = m3u8_url.rsplit("/", 1)[0] + "/"

            ts_urls = []
            for line in m3u8_content.splitlines():
                line = line.strip()
                if line.endswith(".ts") or ".ts?" in line:
                    ts_url = (
                        line if line.startswith("http") else base_url + line
                    )
                    ts_urls.append(ts_url)

            if not ts_urls:
                for line in m3u8_content.splitlines():
                    line = line.strip()
                    if line.endswith(".m3u8") and not line.startswith("#"):
                        sub_url = (
                            line if line.startswith("http") else base_url + line
                        )
                        return await self._download_m3u8(sub_url, output)
                return DownloadResult(
                    success=False, error_code="NO_TS_SEGMENTS"
                )

            logger.info(f"[xiaoe] 下载 {len(ts_urls)} 个 ts 片段")
            output.parent.mkdir(parents=True, exist_ok=True)
            with open(output, "wb") as f:
                for i, ts_url in enumerate(ts_urls):
                    try:
                        resp = await client.get(ts_url)
                        if resp.status_code == 200:
                            f.write(resp.content)
                    except Exception as e:
                        logger.warning(f"[xiaoe] 片段 {i} 下载失败: {e}")
                        continue

            if output.exists() and output.stat().st_size > 1024:
                return DownloadResult(
                    success=True, file_path=output, file_type="ts"
                )
            return DownloadResult(success=False, error_code="EMPTY_OUTPUT")

    async def get_metadata(self, item: ContentItem) -> dict:
        return {"title": item.title, "platform": "xiaoe"}

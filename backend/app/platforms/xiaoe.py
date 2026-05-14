"""小鹅通平台插件"""
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional
from app.services.platform_base import (
    BasePlatform, VideoCapable,
    LoginResult, ContentItem, FetchResult, DownloadResult,
)
from app.services.browser_manager import BrowserManager

logger = logging.getLogger(__name__)


class XiaoEPlugin(BasePlatform, VideoCapable):
    """小鹅通插件

    流程：
    1. 登录：手机验证码登录
    2. 课程列表：访问课程页 → 处理懒加载 → 提取条目
    3. 下载：CDP 拦截 m3u8 请求 → 下载并合并
    """

    LOGIN_URL = "https://appid.xiaoe-tech.com/login"
    COURSE_LIST_URL = "https://appid.xiaoe-tech.com/course_list"

    def __init__(self):
        self.browser_mgr = BrowserManager()

    @property
    def platform(self) -> str:
        return "xiaoe"

    async def login(self, account_id: int) -> LoginResult:
        try:
            pb = await self.browser_mgr.get_browser(self.platform, headless=False)
            page = await pb.new_page()
            await page.goto(self.LOGIN_URL, wait_until="domcontentloaded")

            # 检测是否已有登录态
            await asyncio.sleep(2)
            if "login" not in page.url.lower():
                return LoginResult(success=True)

            # 等待手机验证码登录（最长 180 秒）
            for _ in range(180):
                await asyncio.sleep(1)
                current = page.url
                if "login" not in current.lower():
                    return LoginResult(success=True)
                try:
                    if await page.query_selector(".user-info, [class*='avatar'], [class*='user']"):
                        return LoginResult(success=True)
                except Exception:
                    pass

            return LoginResult(success=False, error_code="TIMEOUT", error_message="登录超时")
        except Exception as e:
            return LoginResult(success=False, error_code="ERROR", error_message=str(e)[:100])

    async def fetch_list(self, page_token: Optional[str] = None) -> FetchResult:
        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        try:
            await page.goto(self.COURSE_LIST_URL, wait_until="networkidle")
            await asyncio.sleep(3)

            items = []
            prev_count = -1
            stable_rounds = 0

            # 处理懒加载：持续滚动直到课程数稳定
            for scroll_attempt in range(15):
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

                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.5)

            logger.info(f"[xiaoe] 检测到 {prev_count} 个课程卡片")

            for card in cards:
                try:
                    title_el = await card.query_selector(
                        ".title, [class*='title'], .name, [class*='name'], h3, h4"
                    )
                    title = await title_el.inner_text() if title_el else "未知课程"
                    title = title.strip()

                    link_el = await card.query_selector("a")
                    link = ""
                    if link_el:
                        link = await link_el.get_attribute("href") or ""

                    item_id = ""
                    if link:
                        m = re.search(r'/([a-zA-Z0-9]{20,})', link)
                        if m:
                            item_id = m.group(1)

                    if not item_id:
                        import hashlib
                        item_id = hashlib.md5(title.encode()).hexdigest()[:12]

                    items.append(ContentItem(
                        platform="xiaoe",
                        item_id=item_id,
                        title=title,
                        content_type="video",
                        url=link if link.startswith("http") else f"https://appid.xiaoe-tech.com{link}",
                    ))
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
        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        m3u8_url = None

        # 拦截 m3u8 请求
        async def intercept_response(response):
            nonlocal m3u8_url
            if response.url.endswith(".m3u8") and "xiaoe" in response.url:
                m3u8_url = response.url
                logger.info(f"[xiaoe] 拦截到 m3u8: {m3u8_url}")

        page.on("response", intercept_response)

        try:
            await page.goto(item.url, wait_until="networkidle")
            await asyncio.sleep(5)

            # 尝试播放
            try:
                play_btn = await page.query_selector(
                    "button:has-text('播放'), .play-btn, [class*='play'], video"
                )
                if play_btn:
                    await play_btn.click()
                    await asyncio.sleep(3)
            except Exception:
                pass

            # 等待 m3u8 请求
            for _ in range(20):
                if m3u8_url:
                    break
                await asyncio.sleep(1)

            if m3u8_url:
                return await self._download_m3u8(m3u8_url, output)

            # 尝试从 video 标签获取 src
            try:
                video_src = await page.evaluate("""() => {
                    const v = document.querySelector('video');
                    return v ? (v.src || v.querySelector('source')?.src) : null;
                }""")
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
                success=False, error_code="NO_M3U8",
                error_message="未捕获到视频流"
            )
        except Exception as e:
            return DownloadResult(
                success=False, error_code="ERROR",
                error_message=str(e)[:200]
            )
        finally:
            page.remove_listener("response", intercept_response)
            await page.close()

    async def _download_m3u8(self, m3u8_url: str, output: Path) -> DownloadResult:
        """下载 m3u8 视频流"""
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(m3u8_url)
            if resp.status_code != 200:
                return DownloadResult(success=False, error_code="M3U8_FETCH_FAIL")

            m3u8_content = resp.text
            base_url = m3u8_url.rsplit("/", 1)[0] + "/"

            # 解析 ts 片段
            ts_urls = []
            for line in m3u8_content.splitlines():
                line = line.strip()
                if line.endswith(".ts") or ".ts?" in line:
                    ts_url = line if line.startswith("http") else base_url + line
                    ts_urls.append(ts_url)

            if not ts_urls:
                # 可能有多层 m3u8（包含不同分辨率）
                for line in m3u8_content.splitlines():
                    line = line.strip()
                    if line.endswith(".m3u8") and not line.startswith("#"):
                        sub_url = line if line.startswith("http") else base_url + line
                        return await self._download_m3u8(sub_url, output)

                return DownloadResult(success=False, error_code="NO_TS_SEGMENTS")

            logger.info(f"[xiaoe] 下载 {len(ts_urls)} 个 ts 片段")

            # 下载并合并
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
                return DownloadResult(success=True, file_path=output, file_type="ts")
            return DownloadResult(success=False, error_code="EMPTY_OUTPUT")

    async def get_metadata(self, item: ContentItem) -> dict:
        return {"title": item.title, "platform": "xiaoe"}

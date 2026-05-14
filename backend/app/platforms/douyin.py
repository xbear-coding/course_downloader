"""抖音平台插件"""
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional
import httpx
from app.services.platform_base import (
    BasePlatform, VideoCapable,
    LoginResult, ContentItem, FetchResult, DownloadResult,
)
from app.services.browser_manager import BrowserManager

logger = logging.getLogger(__name__)


class DouyinPlugin(BasePlatform, VideoCapable):
    """抖音插件

    流程：
    1. 登录：扫码/手机号登录（网页版）
    2. 列表：收藏/喜欢列表
    3. 下载：视频下载（尝试火山引擎 API 或直链）
    """

    DOUYIN_URL = "https://www.douyin.com"

    def __init__(self):
        self.browser_mgr = BrowserManager()

    @property
    def platform(self) -> str:
        return "douyin"

    async def login(self, account_id: int) -> LoginResult:
        try:
            pb = await self.browser_mgr.get_browser(self.platform, headless=False)
            page = await pb.new_page()

            # 抖音网页版强制登录才能查看内容
            await page.goto(self.DOUYIN_URL, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # 检测是否已登录
            try:
                has_login = await page.evaluate("""() => {
                    const avatar = document.querySelector('[class*="avatar"], [class*="Avatar"]');
                    if (avatar) return true;
                    // 检测是否有登录弹窗
                    const loginModal = document.querySelector('[class*="login"], [class*="Login"]');
                    return !loginModal;
                }""")
                if has_login:
                    return LoginResult(success=True)
            except Exception:
                pass

            # 等待扫码/手机登录
            for _ in range(180):
                await asyncio.sleep(1)
                try:
                    has_login = await page.evaluate("""() => {
                        return !!document.querySelector('[class*="avatar"], [class*="Avatar"]');
                    }""")
                    if has_login:
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
            # 访问用户主页或收藏
            user_url = f"{self.DOUYIN_URL}/user/self"
            await page.goto(user_url, wait_until="networkidle")
            await asyncio.sleep(3)

            items = []
            prev_count = -1
            stable_rounds = 0

            for scroll_attempt in range(10):
                cards = await page.query_selector_all(
                    "[class*='video'], [class*='VideoCard'], [class*='feed'], "
                    "[class*='Feed'], [class*='card'], [class*='Card']"
                )
                # 更精确的筛选：查找 video 容器
                actual_items = []
                for card in cards:
                    try:
                        link = await card.get_attribute("href") or ""
                        if link or await card.query_selector("video"):
                            actual_items.append(card)
                    except Exception:
                        continue

                current_count = len(actual_items)
                if current_count == prev_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                prev_count = current_count

                if stable_rounds >= 2:
                    break

                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2)

            seen = set()
            for card in cards:
                try:
                    link_el = await card.query_selector("a[href]")
                    href = ""
                    if link_el:
                        href = await link_el.get_attribute("href") or ""

                    video_id = ""
                    m = re.search(r'/video/(\d+)', href)
                    if m:
                        video_id = m.group(1)

                    if not video_id:
                        # 从当前卡片上下文提取
                        try:
                            video_id = await card.get_attribute("data-id") or ""
                        except Exception:
                            pass

                    if not video_id or video_id in seen:
                        continue
                    seen.add(video_id)

                    title = f"抖音视频 {video_id[:10]}"

                    items.append(ContentItem(
                        platform="douyin",
                        item_id=video_id,
                        title=title,
                        content_type="video",
                        url=f"https://www.douyin.com/video/{video_id}",
                    ))
                except Exception as e:
                    logger.warning(f"[douyin] 解析视频卡片失败: {e}")
                    continue

            return FetchResult(items=items, total_estimated=len(items))

        except Exception as e:
            logger.error(f"[douyin] 获取列表失败: {e}")
            return FetchResult(items=[], partial=True)
        finally:
            await page.close()

    async def download_video(
        self, item: ContentItem, output: Path, quality: str = "720p"
    ) -> DownloadResult:
        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        video_url = None

        # 拦截视频/直播流响应
        async def intercept_response(response):
            nonlocal video_url
            url = response.url
            if any(ext in url for ext in ['.m3u8', '.flv', '.mp4?', 'video/']):
                if not video_url:
                    video_url = url

        page.on("response", intercept_response)

        try:
            await page.goto(item.url, wait_until="networkidle")
            await asyncio.sleep(5)

            # 从 video 标签获取源
            video_url = await page.evaluate("""() => {
                const v = document.querySelector('video');
                if (!v) return null;
                return v.src || '';
            }""")

            if video_url and video_url.startswith("http"):
                async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
                    resp = await client.get(video_url)
                    if resp.status_code == 200:
                        output.write_bytes(resp.content)
                        return DownloadResult(success=True, file_path=output, file_type="mp4")

            # 尝试从页面脚本提取视频地址
            video_info = await page.evaluate(r"""() => {
                const scripts = document.querySelectorAll('script');
                for (const s of scripts) {
                    try {
                        const text = s.textContent || '';
                        if (text.includes('video_id') && text.includes('play_addr')) {
                            const match = text.match(/play_addr["']?:\s*\[?[^]]*["'](https?[^"']+)["']/);
                            if (match) return match[1].replace(/\\u002F/g, '/');
                        }
                        const urlMatch = text.match(/["']src["']?\s*:\s*["'](https?[^"']+\.m3u8[^"']*)["']/);
                        if (urlMatch) return urlMatch[1].replace(/\\u002F/g, '/');
                    } catch(e) {}
                }
                return null;
            }""")

            if video_info:
                video_url = video_info

            if video_url:
                async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
                    resp = await client.get(video_url)
                    if resp.status_code == 200:
                        output.write_bytes(resp.content)
                        return DownloadResult(success=True, file_path=output, file_type="mp4")

            return DownloadResult(success=False, error_code="NO_VIDEO_URL")
        except Exception as e:
            return DownloadResult(success=False, error_code="ERROR", error_message=str(e)[:200])
        finally:
            page.remove_listener("response", intercept_response)
            await page.close()

    async def get_metadata(self, item: ContentItem) -> dict:
        return {"title": item.title, "platform": "douyin"}

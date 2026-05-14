"""腾讯会议平台插件 — 完整实现"""
import asyncio
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

RECORDING_LIST_URL = "https://meeting.tencent.com/user-center/recordings"


class TencentMeetingPlugin(BasePlatform, VideoCapable):
    """腾讯会议插件

    流程：
    1. 登录：打开登录页 → 扫码 → 等待跳转
    2. 录制列表：访问录制中心 → 翻页 → 提取条目
    3. 下载：打开详情页 → 点击导出/下载按钮
    """

    def __init__(self):
        self.browser_mgr = BrowserManager()

    @property
    def platform(self) -> str:
        return "tencent_meeting"

    async def login(self, account_id: int) -> LoginResult:
        try:
            pb = await self.browser_mgr.get_browser(self.platform, headless=False)
            page = await pb.new_page()
            await page.goto("https://meeting.tencent.com/login/", wait_until="domcontentloaded")

            # 检测是否已有登录态
            current = page.url
            if "login" not in current and "passport" not in current:
                return LoginResult(success=True)

            # 等待用户扫码（最长 180 秒）
            for _ in range(180):
                await asyncio.sleep(1)
                current = page.url
                if "login" not in current and "passport" not in current:
                    return LoginResult(success=True)

                # 检查页面是否有"登录成功"或跳转迹象
                try:
                    title = await page.title()
                    if "用户中心" in title or "录制" in title:
                        return LoginResult(success=True)
                except Exception:
                    pass

            return LoginResult(success=False, error_code="TIMEOUT", error_message="扫码超时")
        except Exception as e:
            return LoginResult(success=False, error_code="ERROR", error_message=str(e)[:100])

    async def fetch_list(self, page_token: Optional[str] = None) -> FetchResult:
        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        try:
            url = RECORDING_LIST_URL
            if page_token:
                url = f"{RECORDING_LIST_URL}?page={page_token}"

            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(3)  # 等待列表渲染

            items = []
            # 尝试多种选择器匹配录制列表
            selectors = [
                ".recording-list-item",
                ".record-item",
                "[class*='recording']",
                "[class*='recordItem']",
                "tr[class*='record']",
                ".meeting-list-item",
            ]

            rows = []
            for sel in selectors:
                rows = await page.query_selector_all(sel)
                if rows:
                    logger.info(f"[tencent_meeting] 使用选择器 {sel} 找到 {len(rows)} 条")
                    break

            if not rows:
                # 尝试直接从表格解析
                rows = await page.query_selector_all("table tbody tr")
                if not rows:
                    logger.warning("[tencent_meeting] 未找到录制列表条目")
                    return FetchResult(items=[], partial=True)

            for row in rows:
                try:
                    title_el = await row.query_selector("a, .title, [class*='title'], td:first-child")
                    title = await title_el.inner_text() if title_el else "未知标题"
                    title = title.strip()

                    # 提取链接
                    link = ""
                    if title_el:
                        link = await title_el.get_attribute("href") or ""

                    # 提取录制 ID
                    item_id = ""
                    if link:
                        m = re.search(r'/recording/(\d+)', link)
                        if m:
                            item_id = m.group(1)

                    if not item_id:
                        import hashlib
                        item_id = hashlib.md5(title.encode()).hexdigest()[:12]

                    content_type = "video"
                    items.append(ContentItem(
                        platform="tencent_meeting",
                        item_id=item_id,
                        title=title,
                        content_type=content_type,
                        url=link if link.startswith("http") else f"https://meeting.tencent.com{link}",
                    ))
                except Exception as e:
                    logger.warning(f"[tencent_meeting] 解析条目失败: {e}")
                    continue

            # 检测下一页
            next_token = None
            try:
                next_btn = await page.query_selector(".next-page, [class*='next'], .pagination-next, a[rel='next']")
                if next_btn:
                    disabled = await next_btn.get_attribute("disabled")
                    cls = await next_btn.get_attribute("class") or ""
                    if not disabled and "disabled" not in cls:
                        current_page = int(page_token or 1)
                        next_token = str(current_page + 1)
            except Exception:
                pass

            return FetchResult(items=items, next_token=next_token, total_estimated=len(items))

        except Exception as e:
            logger.error(f"[tencent_meeting] 列表获取失败: {e}")
            return FetchResult(items=[], partial=True)
        finally:
            await page.close()

    async def download_video(
        self, item: ContentItem, output: Path, quality: str = "720p"
    ) -> DownloadResult:
        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        try:
            await page.goto(item.url, wait_until="networkidle")
            await asyncio.sleep(3)

            # 寻找导出/下载按钮
            export_selectors = [
                "button:has-text('导出')",
                "button:has-text('下载')",
                "[class*='export']",
                "[class*='download']",
                "button:has-text('视频')",
            ]

            clicked = False
            for sel in export_selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(2)
                        clicked = True
                        logger.info(f"[tencent_meeting] 点击了 {sel}")
                        break
                except Exception:
                    continue

            if not clicked:
                logger.warning("[tencent_meeting] 未找到导出按钮，尝试检查页面视频元素")

            # 等待下载完成或检测视频源
            await asyncio.sleep(5)

            # 尝试拦截 video 标签的 src
            video_src = None
            try:
                video_el = await page.query_selector("video source, video")
                if video_el:
                    video_src = await video_el.get_attribute("src")
            except Exception:
                pass

            if video_src and video_src.startswith("http"):
                # 直接下载视频文件
                import httpx
                async with httpx.AsyncClient(timeout=300) as client:
                    resp = await client.get(video_src)
                    if resp.status_code == 200:
                        output.write_bytes(resp.content)
                        return DownloadResult(
                            success=True, file_path=output, file_type="ts"
                        )

            # 浏览器触发的下载由 Playwright 自动处理
            # 等待下载事件
            try:
                async with page.expect_download(timeout=30000) as download_info:
                    # 可能已经点击了下载，等待下载开始
                    pass
                download = await download_info.value
                await download.save_as(str(output))
                return DownloadResult(
                    success=True, file_path=output, file_type=output.suffix.lstrip(".") or "mp4"
                )
            except Exception:
                pass

            return DownloadResult(
                success=False, error_code="DOWNLOAD_FAILED",
                error_message="无法捕获视频下载"
            )
        except Exception as e:
            return DownloadResult(
                success=False, error_code="ERROR",
                error_message=str(e)[:200]
            )
        finally:
            await page.close()

    async def get_metadata(self, item: ContentItem) -> dict:
        return {"title": item.title, "platform": "tencent_meeting"}

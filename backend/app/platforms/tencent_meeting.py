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

RECORDING_LIST_URL = "https://meeting.tencent.com/user-center/meeting-record"


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

    async def _check_logged_in(self, page) -> bool:
        """通过多种方式检测是否已登录"""
        # 方式 1: URL 检测（适用于跳转到非登录页面）
        url = page.url
        if "login" not in url and "passport" not in url:
            return True
        # 方式 2: DOM 检测（腾讯会议 SPA 不跳转 URL，但 DOM 会变）
        try:
            # 登录后页面上会有用户头像/信息元素
            user_els = await page.query_selector_all(
                '[class*="avatar"], [class*="Avatar"], '
                '[class*="user-info"], [class*="userInfo"], '
                '[class*="login-status"], button:has-text("退出"), '
                '[class*="header-user"], [class*="userAvatar"]'
            )
            if user_els:
                return True
            # 检查是否有"退出登录"文本，登录后才出现
            body_text = await page.inner_text("body")
            if "退出登录" in body_text or "退出" in body_text:
                return True
        except Exception:
            pass
        return False

    async def login(self, account_id: int) -> LoginResult:
        try:
            pb = await self.browser_mgr.get_browser(self.platform, headless=False)
            page = await pb.new_page()
            await page.goto("https://meeting.tencent.com/login/", wait_until="domcontentloaded")
            await asyncio.sleep(2)

            # 检测是否已有登录态（Chrome Profile 持久化）
            if await self._check_logged_in(page):
                return LoginResult(success=True)

            # 等待用户扫码（最长 180 秒）
            for _ in range(180):
                await asyncio.sleep(1)
                if await self._check_logged_in(page):
                    return LoginResult(success=True)

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

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception:
                logger.warning("[tencent_meeting] 录制列表页加载超时，尝试继续解析")
            await asyncio.sleep(5)

            items = []

            # 方案 1: 通过 data table body 中的 tr 查找
            rows = await page.query_selector_all(".met-table__body tr, table[class*=table] tbody tr, tr[class*=record]")
            if not rows:
                # 方案 2: 通过纯文本查找录制条目
                rows = await page.query_selector_all("table tbody tr, tr[data-row]")

            if rows and len(rows) <= 1:
                rows = []  # 只有表头或空

            if not rows:
                # 方案 3: 通过 JS 直接提取结构化的录制数据
                data = await page.evaluate("""() => {
                    const results = [];
                    // 找到包含录制信息的行
                    const rows = document.querySelectorAll('tr');
                    for (const row of rows) {
                        const cells = row.querySelectorAll('td');
                        if (cells.length < 2) continue;
                        const text = row.textContent.trim();
                        // 跳过表头行
                        if (text.includes('文件') && text.includes('录制时间') && text.includes('文件大小')) continue;
                        if (text.includes('会议') || text.includes('录制')) {
                            const links = row.querySelectorAll('a');
                            const titleEl = row.querySelector('[class*=titleContent], [class*=titleBox]');
                            const title = titleEl ? titleEl.textContent.trim() : cells[0].textContent.trim();
                            const firstLink = links[0] ? links[0].getAttribute('href') || '' : '';
                            results.push({ title, link: firstLink, text: text.slice(0, 200) });
                        }
                    }
                    return results;
                }""")
                for d in data:
                    item_id = d.get('link', '')
                    m = re.search(r'/(\d+)', item_id)
                    if m:
                        item_id = m.group(1)
                    if not item_id:
                        import hashlib
                        item_id = hashlib.md5(d['title'].encode()).hexdigest()[:12]
                    items.append(ContentItem(
                        platform="tencent_meeting",
                        item_id=item_id,
                        title=d['title'][:100],
                        content_type="video",
                        url=d['link'] if d['link'].startswith("http") else f"https://meeting.tencent.com{d['link']}",
                    ))

            if rows:
                for row in rows:
                    try:
                        # 尝试通过 JS 提取行数据
                        row_data = await page.evaluate("""(row) => {
                            const titleEl = row.querySelector('[class*=titleContent]');
                            const linkEl = row.querySelector('a');
                            return {
                                title: titleEl ? titleEl.textContent.trim() : (row.querySelector('td') ? row.querySelector('td').textContent.trim() : ''),
                                link: linkEl ? linkEl.getAttribute('href') || '' : ''
                            };
                        }""", row)
                    except Exception:
                        continue

                    title = row_data.get('title', '').strip()
                    if not title or title.startswith('文件'):
                        continue

                    link = row_data.get('link', '')
                    item_id = ""
                    m = re.search(r'/(\d+)', link)
                    if m:
                        item_id = m.group(1)
                    if not item_id:
                        import hashlib
                        item_id = hashlib.md5(title.encode()).hexdigest()[:12]

                    items.append(ContentItem(
                        platform="tencent_meeting",
                        item_id=item_id,
                        title=title[:100],
                        content_type="video",
                        url=link if link.startswith("http") else f"https://meeting.tencent.com{link}",
                    ))

            if not items:
                logger.warning("[tencent_meeting] 未找到录制列表条目")
                return FetchResult(items=[], partial=True)

            return FetchResult(items=items, total_estimated=len(items))

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
            await page.goto(RECORDING_LIST_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(5)

            # 使用 Playwright 原生 click（JS element.click() 触不了 React 事件）
            more_icons = await page.query_selector_all('[class*=more--outlined]')
            if not more_icons:
                return DownloadResult(
                    success=False, error_code="NO_MORE_BUTTON",
                    error_message="未找到更多按钮",
                )
            await more_icons[-1].click()

            await asyncio.sleep(1.5)

            dl_option = await page.query_selector('[class*=met-list--option] li:first-child')
            if not dl_option:
                return DownloadResult(
                    success=False, error_code="NO_DOWNLOAD_OPTION",
                    error_message="未找到下载选项",
                )
            await dl_option.click()

            await asyncio.sleep(2)

            try:
                async with page.expect_download(timeout=120000) as download_info:
                    pass
                download = await download_info.value
                await download.save_as(str(output))
                return DownloadResult(
                    success=True, file_path=output,
                    file_type=output.suffix.lstrip(".") or "mp4",
                )
            except Exception as e:
                logger.warning(f"[tencent_meeting] 下载未捕获: {e}")
                return DownloadResult(
                    success=False, error_code="DOWNLOAD_TIMEOUT",
                    error_message="下载超时或未触发",
                )

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

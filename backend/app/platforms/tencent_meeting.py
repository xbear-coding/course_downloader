"""腾讯会议平台插件 — API 录制列表 + 详情页文字提取 + 视频导出"""
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

RECORDING_LIST_URL = "https://meeting.tencent.com/user-center/meeting-record"
USER_CENTER = "https://meeting.tencent.com/user-center"


class TencentMeetingPlugin(BasePlatform, VideoCapable):
    """腾讯会议插件

    流程：
    1. 登录：Playwright 扫码（Chrome Profile 持久化）
    2. 录制列表：拦截 API → 提取完整数据（含 share_url_short）
    3. 文字导出：通过 share_url 访问详情页 → 提取 纪要/时间轴/逐字稿 → .md
    4. 视频导出：best-effort（免费版通常无权限）
    """

    def __init__(self):
        self.browser_mgr = BrowserManager()
        self._api_records: list[dict] = []  # 缓存的 API 数据

    @property
    def platform(self) -> str:
        return "tencent_meeting"

    async def _check_logged_in(self, page) -> bool:
        """多维度检测是否已登录"""
        url = page.url
        if "login" not in url and "passport" not in url:
            return True
        try:
            user_els = await page.query_selector_all(
                '[class*="avatar"], [class*="Avatar"], '
                '[class*="user-info"], [class*="userInfo"]'
            )
            if user_els:
                return True
            body = await page.inner_text("body")
            if "退出登录" in body:
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
            if await self._check_logged_in(page):
                return LoginResult(success=True)
            for _ in range(180):
                await asyncio.sleep(1)
                if await self._check_logged_in(page):
                    return LoginResult(success=True)
            return LoginResult(success=False, error_code="TIMEOUT", error_message="扫码超时")
        except Exception as e:
            return LoginResult(success=False, error_code="ERROR", error_message=str(e)[:100])

    async def fetch_list(self, page_token: Optional[str] = None) -> FetchResult:
        """获取录制列表（拦截 API 获取结构化数据）"""
        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        api_data = []

        async def capture_api(response):
            if "my-record-list" in response.url:
                try:
                    body = await response.json()
                    records = body.get("data", {}).get("records", [])
                    api_data.extend(records)
                except Exception:
                    pass

        page.on("response", capture_api)

        try:
            await page.goto(RECORDING_LIST_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(5)
        except Exception:
            await asyncio.sleep(5)

        if not api_data:
            logger.warning("[tencent_meeting] 未捕获到 API 数据")
            return FetchResult(items=[], partial=True)

        self._api_records = api_data
        items = []

        for r in api_data:
            title = r.get("title", "") or "未知会议"
            record_id = r.get("record_id", "") or r.get("uni_record_id", "")
            share_code = (r.get("share_url_short", "") or "").replace("crm/", "").replace("ctm/", "")
            jump_path = r.get("jump_path_short", "")
            size = int(r.get("size", 0))
            is_video = r.get("is_video", False) or size > 0
            record_type = r.get("record_type", "")

            items.append(ContentItem(
                platform="tencent_meeting",
                item_id=record_id,
                title=title[:200],
                content_type="video" if is_video else "article",
                url=f"https://meeting.tencent.com/{r.get('share_url_short', '')}",
                metadata={
                    "share_code": share_code,
                    "jump_path": jump_path,
                    "uni_record_id": r.get("uni_record_id", ""),
                    "size": size,
                    "duration": r.get("duration", "0"),
                    "record_type": record_type,
                    "share_url": r.get("share_url", ""),
                },
            ))

        return FetchResult(items=items, total_estimated=len(items))

    async def extract_texts(
        self, item: ContentItem, output_dir: Path
    ) -> dict[str, Path]:
        """从详情页提取 纪要/时间轴/逐字稿，保存为 .md 文件

        返回: {"summary": Path, "timeline": Path, "transcript": Path}
        """
        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        share_code = item.metadata.get("share_code", "")
        if not share_code:
            logger.warning("[tencent_meeting] 无 share_code，无法提取文字")
            return {}

        result_paths = {}

        try:
            # 通过 share URL 访问详情页
            await page.goto(
                f"https://meeting.tencent.com/crm/{share_code}",
                wait_until="domcontentloaded", timeout=20000,
            )
            await asyncio.sleep(4)

            # 提取当前页面的文字内容
            # 页面默认显示"智能转写" Tab，含发言人/AI总结等
            body_text = await page.inner_text("body")

            # 切换 Tab 并提取
            tabs = [
                ("summary", "纪要"),
                ("timeline", "时间轴"),
                ("transcript", "逐字稿"),
            ]

            for key, tab_name in tabs:
                tab_path = await self._switch_tab_and_extract(page, tab_name, item, output_dir)
                if tab_path:
                    result_paths[key] = tab_path

            # 如果 tab 提取都没内容，把当前页面的 text 内容存为 transcript
            if not result_paths:
                clean_lines = [l.strip() for l in body_text.split("\n") if l.strip()]
                if clean_lines and len(clean_lines) > 5:
                    md = "# " + item.title + "\n\n" + "\n\n".join(clean_lines)
                    out_path = output_dir / f"{item.item_id}_transcript.md"
                    out_path.write_text(md, encoding="utf-8")
                    result_paths["transcript"] = out_path

        except Exception as e:
            logger.warning(f"[tencent_meeting] 文字提取失败: {e}")
        finally:
            await page.close()

        return result_paths

    async def _switch_tab_and_extract(
        self, page, tab_name: str, item: ContentItem, output_dir: Path
    ) -> Optional[Path]:
        """切换 Tab 并提取内容"""
        # 通过 JS 点击 Tab
        clicked = await page.evaluate(f"""(name) => {{
            const buttons = document.querySelectorAll('button');
            for (const b of buttons) {{
                if (b.textContent.trim() === name && b.offsetHeight > 0) {{
                    b.scrollIntoView({{block:'center'}});
                    b.click();
                    return true;
                }}
            }}
            return false;
        }}""", tab_name)

        if not clicked:
            return None

        await asyncio.sleep(3)

        # 提取 Tab 面板内容
        content = await page.evaluate("""(name) => {
            // Find active/visible panel content
            const panels = document.querySelectorAll('[class*=tab-panel-container] [class*=content], [class*=tab-panel-content]');
            for (const p of panels) {
                if (p.offsetHeight > 0) {
                    return p.innerText;
                }
            }
            // Fallback: all visible text
            return document.body.innerText;
        }""", tab_name)

        if not content or len(content.strip()) < 10:
            return None

        # 保存为 .md
        key_map = {"纪要": "summary", "时间轴": "timeline", "逐字稿": "transcript"}
        file_key = key_map.get(tab_name, tab_name)

        content = content.strip()
        md = f"# {item.title} — {tab_name}\n\n{content}"
        out_path = output_dir / f"{item.item_id}_{file_key}.md"
        out_path.write_text(md, encoding="utf-8")
        logger.info(f"[tencent_meeting] 已保存 {tab_name}: {out_path}")
        return out_path

    async def download_video(
        self, item: ContentItem, output: Path, quality: str = "720p"
    ) -> DownloadResult:
        """导出视频（best-effort，免费版通常无权限）"""
        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        try:
            await page.goto(RECORDING_LIST_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(5)

            # 点击"更多" → 下载
            more_icons = await page.locator('[class*=more--outlined]').all()
            if more_icons:
                await more_icons[0].click()
                await asyncio.sleep(1.5)

                dl_option = await page.query_selector('[class*=met-list--option] li:first-child')
                if dl_option:
                    await dl_option.click()
                    await asyncio.sleep(2)

                    # 监听下载事件
                    download_event = None
                    def on_dl(dl):
                        nonlocal download_event
                        download_event = dl
                    page.on("download", on_dl)

                    for _ in range(30):
                        await asyncio.sleep(1)
                        if download_event:
                            break

                    if download_event:
                        page.remove_listener("download", on_dl)
                        await download_event.save_as(str(output))
                        return DownloadResult(
                            success=True, file_path=output,
                            file_type=output.suffix.lstrip(".") or "mp4",
                        )
                    page.remove_listener("download", on_dl)

            # 检查是否弹出了分享对话框（权限限制）
            share_modal = await page.query_selector('[class*=ShareModal]')
            if share_modal:
                return DownloadResult(
                    success=False, error_code="DOWNLOAD_DISABLED",
                    error_message="视频下载需要权限（免费版限制）",
                )

            return DownloadResult(
                success=False, error_code="DOWNLOAD_FAILED",
                error_message="视频导出不可用",
            )
        except Exception as e:
            return DownloadResult(
                success=False, error_code="ERROR", error_message=str(e)[:200],
            )
        finally:
            await page.close()

    async def get_metadata(self, item: ContentItem) -> dict:
        return {"title": item.title, "platform": "tencent_meeting"}

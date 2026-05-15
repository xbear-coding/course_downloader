"""腾讯会议平台插件 — API 录制列表 + /cw/ 详情页视频直链下载"""
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


class TencentMeetingPlugin(BasePlatform, VideoCapable):
    def __init__(self):
        self.browser_mgr = BrowserManager()
        self._api_records: list[dict] = []

    @property
    def platform(self) -> str:
        return "tencent_meeting"

    async def _check_logged_in(self, page) -> bool:
        url = page.url
        if "login" not in url and "passport" not in url:
            return True
        try:
            user_els = await page.query_selector_all(
                '[class*="avatar"], [class*="Avatar"], [class*="user-info"]'
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
            return FetchResult(items=[], partial=True)

        self._api_records = api_data
        items = []
        for r in api_data:
            title = r.get("title", "") or "未知会议"
            record_id = r.get("record_id", "") or r.get("uni_record_id", "")
            share_code = (r.get("share_url_short", "") or "").replace("crm/", "").replace("ctm/", "")
            size = int(r.get("size", 0))
            is_video = r.get("is_video", False) or size > 0
            items.append(ContentItem(
                platform="tencent_meeting",
                item_id=record_id,
                title=title[:200],
                content_type="video" if is_video else "article",
                url=f"https://meeting.tencent.com/{r.get('share_url_short', '')}",
                metadata={
                    "share_code": share_code,
                    "jump_path": r.get("jump_path_short", ""),
                    "uni_record_id": r.get("uni_record_id", ""),
                    "size": size,
                    "duration": r.get("duration", "0"),
                    "record_type": r.get("record_type", ""),
                },
            ))
        return FetchResult(items=items, total_estimated=len(items))

    async def extract_texts(self, item: ContentItem, output_dir: Path) -> dict[str, Path]:
        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()
        share_code = item.metadata.get("share_code", "")
        if not share_code:
            return {}

        result_paths = {}
        try:
            await page.goto(f"https://meeting.tencent.com/crm/{share_code}",
                            wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(4)

            for key, tab_name in [("summary", "纪要"), ("timeline", "时间轴"), ("transcript", "逐字稿")]:
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
                    continue
                await asyncio.sleep(3)

                content = await page.evaluate("""() => {
                    const panel = document.querySelector('[class*=tab-panel-container] [class*=content]');
                    if (panel && panel.offsetHeight > 0) return panel.innerText;
                    return '';
                }""")
                if content and len(content.strip()) > 10:
                    out_path = output_dir / f"{item.item_id}_{key}.md"
                    out_path.write_text(f"# {item.title} — {tab_name}\n\n{content.strip()}", encoding="utf-8")
                    result_paths[key] = out_path

            if not result_paths:
                body = await page.inner_text("body")
                lines = [l.strip() for l in body.split("\n") if l.strip()]
                if lines and len(lines) > 5:
                    out_path = output_dir / f"{item.item_id}_transcript.md"
                    out_path.write_text(f"# {item.title}\n\n" + "\n\n".join(lines), encoding="utf-8")
                    result_paths["transcript"] = out_path
        except Exception as e:
            logger.warning(f"[tencent_meeting] 文字提取失败: {e}")
        finally:
            await page.close()
        return result_paths

    async def download_video(self, item: ContentItem, output: Path, quality: str = "720p") -> DownloadResult:
        """通过 /cw/ 详情页获取视频直链下载"""
        share_code = item.metadata.get("share_code", "")
        if not share_code:
            return DownloadResult(success=False, error_code="NO_SHARE_CODE", error_message="无 share_code")

        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        try:
            await page.goto(f"https://meeting.tencent.com/crm/{share_code}",
                            wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(5)

            video_src = await page.evaluate("""() => {
                const v = document.querySelector('video');
                return v ? (v.currentSrc || v.src || '') : '';
            }""")

            if not video_src:
                return DownloadResult(success=False, error_code="NO_VIDEO_SRC", error_message="未找到视频源")

            # anchor click 触发下载
            dl_event = []
            def on_dl(dl):
                dl_event.append(dl)
            page.on("download", on_dl)

            await page.evaluate(f"""(url) => {{
                const a = document.createElement('a');
                a.href = url;
                a.download = 'meeting_recording.mp4';
                a.style.display = 'none';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
            }}""", video_src)

            for _ in range(30):
                await asyncio.sleep(1)
                if dl_event:
                    break

            if dl_event:
                page.remove_listener("download", on_dl)
                await dl_event[0].save_as(str(output))
                return DownloadResult(success=True, file_path=output, file_type="mp4")

            page.remove_listener("download", on_dl)
            return DownloadResult(success=False, error_code="DOWNLOAD_TIMEOUT", error_message="下载未触发")
        except Exception as e:
            return DownloadResult(success=False, error_code="ERROR", error_message=str(e)[:200])
        finally:
            await page.close()

    async def get_metadata(self, item: ContentItem) -> dict:
        return {"title": item.title, "platform": "tencent_meeting"}

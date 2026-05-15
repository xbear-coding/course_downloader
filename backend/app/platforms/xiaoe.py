"""小鹅通平台插件 — API 直调（非 React 点击）"""
import asyncio
import json
import logging
import re
import httpx
from pathlib import Path
from typing import Optional, Dict
from app.services.platform_base import (
    BasePlatform, VideoCapable,
    LoginResult, ContentItem, FetchResult, DownloadResult,
)
from app.services.browser_manager import BrowserManager
from app.database import async_session

logger = logging.getLogger(__name__)

APP_ID = "app5vfffdhz8371"
COLUMN_ID = "p_60f40504e4b08f7ad23e0e60"
API_BASE = f"https://{APP_ID}.xet-pc.citv.cn"
COURSE_LIST_URL = f"{API_BASE}/xe.course.business_go.column.items.get/2.0.0"
VIDEO_DETAIL_URL = f"{API_BASE}/xe.course.business_go.video_detail.get/2.0.0"
WEB_BASE = f"https://{APP_ID}.pc.xiaoe-tech.com"


async def _load_cookies() -> Dict[str, str]:
    import json as _json
    from app.models import Account
    async with async_session() as db:
        acct = await db.get(Account, 3)
        if acct and acct.cookie_file and acct.cookie_file.startswith("xiaoe_c:"):
            try:
                return _json.loads(acct.cookie_file.split(":", 1)[1])
            except Exception:
                pass
    return {}


async def _save_cookies(cookies: Dict[str, str]):
    import json as _json
    from app.models import Account
    async with async_session() as db:
        acct = await db.get(Account, 3)
        if acct:
            acct.cookie_file = f"xiaoe_c:{_json.dumps(cookies, ensure_ascii=False)}"
            await db.commit()


class XiaoEPlugin(BasePlatform, VideoCapable):
    def __init__(self):
        self.browser_mgr = BrowserManager()
        self._cookies: Dict[str, str] = {}

    @property
    def platform(self) -> str:
        return "xiaoe"

    async def login(self, account_id: int) -> LoginResult:
        # Try loading cached cookies first
        self._cookies = await _load_cookies()
        if self._cookies:
            return LoginResult(success=True)

        try:
            pb = await self.browser_mgr.get_browser(self.platform, headless=False)
            page = await pb.new_page()
            await page.goto(f"{WEB_BASE}/p/t_pc/course_pc_detail/column/{COLUMN_ID}",
                            wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)

            body = await page.inner_text("body")
            if "退出" in body or "我的课程" in body:
                await self._extract_cookies(page)
                return LoginResult(success=True)

            for i in range(300):
                await asyncio.sleep(1)
                try:
                    body = await page.inner_text("body")
                    if "退出" in body or "我的课程" in body:
                        await self._extract_cookies(page)
                        return LoginResult(success=True)
                except Exception:
                    pass
                if i % 30 == 0:
                    logger.info(f"[xiaoe] 等待登录... {i}s")

            return LoginResult(success=False, error_code="TIMEOUT", error_message="登录超时")
        except Exception as e:
            return LoginResult(success=False, error_code="ERROR", error_message=str(e)[:100])

    async def _extract_cookies(self, page):
        cookies = await page.context.cookies()
        self._cookies = {c["name"]: c["value"] for c in cookies}
        await _save_cookies(self._cookies)
        logger.info(f"[xiaoe] 已提取并持久化 {len(self._cookies)} 个 cookie")

    async def _api_request(self, url: str, data: dict) -> dict:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": API_BASE,
            "Referer": f"{WEB_BASE}/",
        }
        async with httpx.AsyncClient(timeout=15, headers=headers) as c:
            c.cookies.update(self._cookies)
            r = await c.post(url, data=data)
            if r.status_code != 200:
                raise RuntimeError(f"API {r.status_code}: {r.text[:200]}")
            return r.json()

    async def fetch_list(self, page_token: Optional[str] = None) -> FetchResult:
        if not self._cookies:
            self._cookies = await _load_cookies()
        if not self._cookies:
            return FetchResult(items=[], partial=True)

        items = []
        page = int(page_token or 1)

        try:
            result = await self._api_request(COURSE_LIST_URL, {
                "column_id": COLUMN_ID, "page": str(page), "size": "50",
            })

            api_items = result.get("data", {}).get("list", []) or result.get("data", {}).get("items", [])

            for api_item in api_items:
                resource_id = api_item.get("resource_id", "") or api_item.get("ID", "") or api_item.get("id", "")
                title = api_item.get("name", "") or api_item.get("title", "") or api_item.get("resource_name", "")
                if not resource_id or not title:
                    continue
                items.append(ContentItem(
                    platform="xiaoe", item_id=resource_id, title=title.strip()[:200],
                    content_type="video",
                    url=f"{WEB_BASE}/p/t_pc/course_pc_detail/column/{COLUMN_ID}?rid={resource_id}",
                ))

            return FetchResult(items=items, total_estimated=len(items), next_token=str(page + 1) if len(api_items) >= 50 else None)
        except Exception as e:
            logger.error(f"[xiaoe] API获取课程列表失败: {e}")
            return FetchResult(items=[], partial=True)

    async def download_video(self, item: ContentItem, output: Path, quality: str = "720p") -> DownloadResult:
        if not self._cookies:
            self._cookies = await _load_cookies()
        if not self._cookies:
            return DownloadResult(success=False, error_code="NO_AUTH", error_message="未登录")

        try:
            detail = await self._api_request(VIDEO_DETAIL_URL, {
                "resource_id": item.item_id, "resource_app_id": APP_ID,
            })

            video_url = None
            data = detail.get("data", {})
            for key in ["video_url", "play_url", "stream_url", "url", "m3u8_url"]:
                if key in data and data[key]:
                    video_url = data[key]
                    break
            content = data.get("content", {})
            if isinstance(content, dict) and not video_url:
                for key in ["video_url", "play_url", "url"]:
                    if key in content and content[key]:
                        video_url = content[key]
                        break

            if not video_url:
                return DownloadResult(success=False, error_code="NO_VIDEO_URL", error_message=f"API未返回视频URL")

            if ".m3u8" in video_url:
                return await self._download_m3u8(video_url, output)
            else:
                async with httpx.AsyncClient(timeout=300, follow_redirects=True) as c:
                    c.cookies.update(self._cookies)
                    r = await c.get(video_url)
                    if r.status_code == 200 and len(r.content) > 1024:
                        output.write_bytes(r.content)
                        return DownloadResult(success=True, file_path=output, file_type=output.suffix.lstrip(".") or "mp4")
                return DownloadResult(success=False, error_code="DOWNLOAD_FAIL")
        except Exception as e:
            return DownloadResult(success=False, error_code="ERROR", error_message=str(e)[:200])

    async def _download_m3u8(self, m3u8_url: str, output: Path) -> DownloadResult:
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                c.cookies.update(self._cookies)
                resp = await c.get(m3u8_url)
                if resp.status_code != 200:
                    return DownloadResult(success=False, error_code="M3U8_FETCH_FAIL")
                content = resp.text
                base = m3u8_url.rsplit("/", 1)[0] + "/"
                for line in content.splitlines():
                    line = line.strip()
                    if line.endswith(".m3u8") and not line.startswith("#"):
                        sub_url = line if line.startswith("http") else base + line
                        return await self._download_m3u8(sub_url, output)
                ts_urls = []
                for line in content.splitlines():
                    line = line.strip()
                    if line.endswith(".ts") or ".ts?" in line:
                        ts_urls.append(line if line.startswith("http") else base + line)
                if not ts_urls:
                    return DownloadResult(success=False, error_code="NO_TS")
                output.parent.mkdir(parents=True, exist_ok=True)
                with open(output, "wb") as f:
                    for ts_url in ts_urls:
                        try:
                            r = await c.get(ts_url, timeout=30)
                            if r.status_code == 200:
                                f.write(r.content)
                        except Exception:
                            continue
                if output.exists() and output.stat().st_size > 1024:
                    return DownloadResult(success=True, file_path=output, file_type="ts")
                return DownloadResult(success=False, error_code="EMPTY")
        except Exception as e:
            return DownloadResult(success=False, error_code="M3U8_ERROR", error_message=str(e)[:200])

    async def get_metadata(self, item: ContentItem) -> dict:
        return {"title": item.title, "platform": "xiaoe"}

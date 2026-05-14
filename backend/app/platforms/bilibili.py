"""B站平台插件"""
import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
import urllib.parse
from pathlib import Path
from typing import Optional
import httpx
from app.services.platform_base import (
    BasePlatform, VideoCapable, SubtitleCapable,
    LoginResult, ContentItem, FetchResult, DownloadResult,
)
from app.services.browser_manager import BrowserManager

logger = logging.getLogger(__name__)

BILIBILI_API_BASE = "https://api.bilibili.com"
BILIBILI_PASSPORT = "https://passport.bilibili.com"


class BilibiliPlugin(BasePlatform, VideoCapable, SubtitleCapable):
    """B站插件

    流程：
    1. 登录：扫码/密码登录
    2. 列表：UP 主视频或收藏夹
    3. 下载：API 获取视频流 → ffmpeg 合并
    4. 字幕：API 获取 CC 字幕
    """

    def __init__(self):
        self.browser_mgr = BrowserManager()
        self._cookies: dict = {}

    @property
    def platform(self) -> str:
        return "bilibili"

    async def login(self, account_id: int) -> LoginResult:
        try:
            pb = await self.browser_mgr.get_browser(self.platform, headless=False)
            page = await pb.new_page()
            await page.goto(f"{BILIBILI_PASSPORT}/login", wait_until="domcontentloaded")

            await asyncio.sleep(2)
            if "login" not in page.url.lower():
                return LoginResult(success=True)

            # 等待扫码登录（最长 180 秒）
            for _ in range(180):
                await asyncio.sleep(1)
                current = page.url
                if "login" not in current.lower():
                    # 登录成功，提取 cookies
                    cookies = await page.context.cookies()
                    for c in cookies:
                        self._cookies[c["name"]] = c["value"]
                    return LoginResult(success=True)

            return LoginResult(success=False, error_code="TIMEOUT", error_message="扫码超时")
        except Exception as e:
            return LoginResult(success=False, error_code="ERROR", error_message=str(e)[:100])

    async def fetch_list(self, page_token: Optional[str] = None) -> FetchResult:
        from app.database import async_session
        from app.models import Account
        from sqlalchemy import select

        items = []
        page = int(page_token or 1)
        page_size = 30

        async with async_session() as db:
            acct = (
                await db.execute(
                    select(Account).where(
                        Account.platform_id == 2,  # bilibili
                        Account.is_active == True,
                    )
                )
            ).scalar_one_or_none()

        if not acct:
            return FetchResult(items=[], partial=True)

        # 获取用户 mid（需要 cookies 环境）
        try:
            params = {"ps": page_size, "pn": page}
            headers = self._build_headers()

            async with httpx.AsyncClient(timeout=15) as client:
                # 先获取用户信息
                resp = await client.get(
                    f"{BILIBILI_API_BASE}/x/web-interface/nav",
                    headers=headers,
                )
                if resp.status_code != 200:
                    return FetchResult(items=[], partial=True)
                nav_data = resp.json()
                mid = nav_data.get("data", {}).get("mid", 0)
                if not mid:
                    return FetchResult(items=[], partial=True)

                # 获取用户投稿视频
                resp2 = await client.get(
                    f"{BILIBILI_API_BASE}/x/space/wbi/arc/search",
                    params={"mid": mid, "ps": page_size, "pn": page},
                    headers=headers,
                )
                if resp2.status_code != 200:
                    return FetchResult(items=[], partial=True)

                data = resp2.json().get("data", {})
                vlist = data.get("list", {}).get("vlist", [])

                if not vlist:
                    # 新版 API 字段名不同
                    vlist = data.get("list", []) or []

                for v in vlist:
                    aid = str(v.get("aid") or v.get("bvid", ""))
                    if not aid:
                        continue
                    items.append(ContentItem(
                        platform="bilibili",
                        item_id=aid,
                        title=v.get("title", "未知视频"),
                        content_type="video",
                        url=f"https://www.bilibili.com/video/{v.get('bvid', aid)}",
                        metadata={
                            "bvid": v.get("bvid", ""),
                            "duration": v.get("duration", 0),
                        },
                    ))

                # 分页
                total = data.get("page", {}).get("count", 0) or data.get("total", 0)
                has_next = page * page_size < total
                next_token = str(page + 1) if has_next else None

                return FetchResult(items=items, next_token=next_token, total_estimated=total)

        except Exception as e:
            logger.error(f"[bilibili] 获取列表失败: {e}")
            return FetchResult(items=[], partial=True)

    async def download_video(
        self, item: ContentItem, output: Path, quality: str = "720p"
    ) -> DownloadResult:
        try:
            headers = self._build_headers()
            bvid = item.metadata.get("bvid", item.item_id)

            async with httpx.AsyncClient(timeout=30) as client:
                # 获取视频播放地址
                params = {}
                if bvid.startswith("BV"):
                    params["bvid"] = bvid
                else:
                    params["avid"] = item.item_id

                resp = await client.get(
                    f"{BILIBILI_API_BASE}/x/player/wbi/playurl",
                    params={**params, "qn": 80, "fnval": 4048},
                    headers=headers,
                )
                if resp.status_code != 200:
                    return DownloadResult(success=False, error_code="API_FAIL")

                data = resp.json().get("data", {})
                dash = data.get("dash", {})

                # 优先 DASH 流
                video_url = None
                audio_url = None

                if dash:
                    videos = dash.get("video", [])
                    audios = dash.get("audio", [])

                    # 选择最接近目标质量的视频流
                    qn_map = {"360p": 32, "480p": 64, "720p": 80, "1080p": 120}
                    target_id = qn_map.get(quality, 80)

                    best_video = None
                    for v in videos:
                        if v.get("id", 0) <= target_id:
                            if not best_video or v.get("id", 0) > best_video.get("id", 0):
                                best_video = v

                    video_url = best_video.get("baseUrl", "") if best_video else ""
                    audio_url = audios[0].get("baseUrl", "") if audios else ""

                if not video_url:
                    # 回退到 DURL（旧格式）
                    durl = data.get("durl", [])
                    if durl:
                        video_url = durl[0].get("url", "")
                        audio_url = None  # 旧格式已包含音频

                if not video_url:
                    return DownloadResult(success=False, error_code="NO_VIDEO_URL")

                output.parent.mkdir(parents=True, exist_ok=True)

                if audio_url:
                    # 分别下载音视频后用 ffmpeg 合并
                    video_tmp = output.with_suffix(".video.mp4")
                    audio_tmp = output.with_suffix(".audio.mp4")

                    await self._download_file(client, video_url, video_tmp, headers)
                    await self._download_file(client, audio_url, audio_tmp, headers)

                    # ffmpeg 合并
                    from app.services.media_converter import ts_to_mp4
                    import asyncio

                    cmd = [
                        "ffmpeg", "-y",
                        "-i", str(video_tmp),
                        "-i", str(audio_tmp),
                        "-c:v", "copy",
                        "-c:a", "aac",
                        str(output),
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                    )
                    await proc.communicate()

                    video_tmp.unlink(missing_ok=True)
                    audio_tmp.unlink(missing_ok=True)

                    if output.exists():
                        return DownloadResult(success=True, file_path=output, file_type="mp4")

                # 单个流直接下载
                await self._download_file(client, video_url, output, headers)
                if output.exists() and output.stat().st_size > 1024:
                    return DownloadResult(success=True, file_path=output, file_type="mp4")

                return DownloadResult(success=False, error_code="DOWNLOAD_FAILED")

        except Exception as e:
            return DownloadResult(success=False, error_code="ERROR", error_message=str(e)[:200])

    async def download_subtitle(self, item: ContentItem, language: str = "zh") -> str:
        headers = self._build_headers()
        bvid = item.metadata.get("bvid", item.item_id)

        async with httpx.AsyncClient(timeout=15) as client:
            params = {"bvid": bvid} if bvid.startswith("BV") else {"avid": item.item_id}
            resp = await client.get(
                f"{BILIBILI_API_BASE}/x/player/v2",
                params=params,
                headers=headers,
            )
            if resp.status_code != 200:
                return ""

            data = resp.json().get("data", {})
            subtitle_list = data.get("subtitle", {}).get("subtitles", [])

            for sub in subtitle_list:
                if language in sub.get("lan_doc", "") or sub.get("language") == language:
                    sub_url = sub.get("subtitle_url", "")
                    if sub_url:
                        if sub_url.startswith("//"):
                            sub_url = "https:" + sub_url
                        resp2 = await client.get(sub_url)
                        if resp2.status_code == 200:
                            lines = []
                            for item_data in resp2.json().get("body", []):
                                start = item_data.get("from", 0)
                                content = item_data.get("content", "")
                                h, r = divmod(int(start), 3600)
                                m, s = divmod(r, 60)
                                lines.append(f"**{h:02d}:{m:02d}:{s:02d} →** {content}")
                            return "\n".join(lines)

            return ""

    async def get_metadata(self, item: ContentItem) -> dict:
        headers = self._build_headers()
        bvid = item.metadata.get("bvid", item.item_id)

        async with httpx.AsyncClient(timeout=10) as client:
            params = {"bvid": bvid} if bvid.startswith("BV") else {"avid": item.item_id}
            resp = await client.get(
                f"{BILIBILI_API_BASE}/x/web-interface/view",
                params=params,
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return {
                    "title": data.get("title", ""),
                    "desc": data.get("desc", ""),
                    "duration": data.get("duration", 0),
                    "owner": data.get("owner", {}).get("name", ""),
                }
            return {"title": item.title}

    def _build_headers(self) -> dict:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com",
        }
        if self._cookies:
            cookie_str = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
            headers["Cookie"] = cookie_str
        return headers

    async def _download_file(
        self, client: httpx.AsyncClient, url: str, output: Path, headers: dict
    ):
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            output.write_bytes(resp.content)

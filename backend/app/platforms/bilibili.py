"""B站平台插件（含 WBI 签名 + Cookie 提取）"""
import asyncio
import hashlib
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
from app.database import async_session

logger = logging.getLogger(__name__)

BILIBILI_API_BASE = "https://api.bilibili.com"
BILIBILI_PASSPORT = "https://passport.bilibili.com"

_wbi_keys: dict[str, str] = {}
_wbi_keys_time: float = 0


def _get_mix_key() -> str | None:
    global _wbi_keys, _wbi_keys_time
    if _wbi_keys and time.time() - _wbi_keys_time < 3600:
        return _wbi_keys.get("img_key", "")[:4] + _wbi_keys.get("sub_key", "")[:4]
    return None


async def _update_wbi_keys(headers: dict):
    global _wbi_keys, _wbi_keys_time
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{BILIBILI_API_BASE}/x/web-interface/nav", headers=headers)
            if r.status_code != 200:
                return
            data = r.json().get("data", {})
            wbi_img = data.get("wbi_img", {})
            if wbi_img:
                _wbi_keys = {"img_key": wbi_img.get("img_key", ""), "sub_key": wbi_img.get("sub_key", "")}
                _wbi_keys_time = time.time()
    except Exception:
        pass


def _sign_wbi(params: dict, mix_key: str | None = None) -> dict:
    if not mix_key:
        mix_key = _get_mix_key()
    if not mix_key:
        return params
    signed = dict(params)
    signed["wts"] = int(time.time())
    keys = sorted(signed.keys())
    sorted_params = urllib.parse.urlencode({k: signed[k] for k in keys})
    sign_str = sorted_params + mix_key
    signed["w_rid"] = hashlib.md5(sign_str.encode()).hexdigest()
    return signed


class BilibiliPlugin(BasePlatform, VideoCapable, SubtitleCapable):
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
                await self._extract_cookies(page)
                return LoginResult(success=True)
            for _ in range(180):
                await asyncio.sleep(1)
                if "login" not in page.url.lower():
                    await self._extract_cookies(page)
                    return LoginResult(success=True)
            return LoginResult(success=False, error_code="TIMEOUT", error_message="扫码超时")
        except Exception as e:
            return LoginResult(success=False, error_code="ERROR", error_message=str(e)[:100])

    async def _extract_cookies(self, page):
        cookies = await page.context.cookies()
        self._cookies = {c["name"]: c["value"] for c in cookies}

    async def fetch_list(self, page_token: Optional[str] = None) -> FetchResult:
        items = []
        page = int(page_token or 1)
        page_size = 30

        async with async_session() as db:
            from app.models import Platform as PlatModel, Account
            from sqlalchemy import select
            plat = (await db.execute(select(PlatModel).where(PlatModel.name == "bilibili"))).scalar_one_or_none()
            if not plat:
                return FetchResult(items=[], partial=True)
            acct = (await db.execute(
                select(Account).where(Account.platform_id == plat.id, Account.is_active == True)
            )).scalar_one_or_none()

        if not acct:
            return FetchResult(items=[], partial=True)

        try:
            headers = self._build_headers()
            await _update_wbi_keys(headers)

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{BILIBILI_API_BASE}/x/web-interface/nav", headers=headers)
                if resp.status_code != 200:
                    return FetchResult(items=[], partial=True)
                nav_data = resp.json()
                mid = nav_data.get("data", {}).get("mid", 0)
                if not mid:
                    return FetchResult(items=[], partial=True)

                wbi_params = _sign_wbi({"mid": mid, "ps": page_size, "pn": page})
                resp2 = await client.get(
                    f"{BILIBILI_API_BASE}/x/space/wbi/arc/search",
                    params=wbi_params, headers=headers,
                )
                if resp2.status_code != 200:
                    return FetchResult(items=[], partial=True)

                data = resp2.json().get("data", {})
                vlist = data.get("list", {}).get("vlist", []) or data.get("list", []) or []

                for v in vlist:
                    aid = str(v.get("aid") or v.get("bvid", ""))
                    if not aid:
                        continue
                    items.append(ContentItem(
                        platform="bilibili", item_id=aid,
                        title=v.get("title", "未知视频"), content_type="video",
                        url=f"https://www.bilibili.com/video/{v.get('bvid', aid)}",
                        metadata={"bvid": v.get("bvid", ""), "duration": v.get("duration", 0)},
                    ))

                total = data.get("page", {}).get("count", 0) or data.get("total", 0)
                return FetchResult(items=items, total_estimated=total,
                                  next_token=str(page + 1) if page * page_size < total else None)
        except Exception as e:
            logger.error(f"[bilibili] 获取列表失败: {e}")
            return FetchResult(items=[], partial=True)

    async def download_video(self, item: ContentItem, output: Path, quality: str = "720p") -> DownloadResult:
        try:
            headers = self._build_headers()
            bvid = item.metadata.get("bvid", item.item_id)
            await _update_wbi_keys(headers)

            async with httpx.AsyncClient(timeout=30) as client:
                params = {}
                if bvid.startswith("BV"):
                    params["bvid"] = bvid
                else:
                    params["avid"] = item.item_id
                params["qn"] = 80
                params["fnval"] = 4048

                signed_params = _sign_wbi(params)
                resp = await client.get(
                    f"{BILIBILI_API_BASE}/x/player/wbi/playurl",
                    params=signed_params, headers=headers,
                )
                if resp.status_code != 200:
                    return DownloadResult(success=False, error_code="API_FAIL",
                                          error_message=f"B站API返回{resp.status_code}")
                data = resp.json().get("data", {})
                dash = data.get("dash", {})
                video_url, audio_url = None, None

                if dash:
                    videos, audios = dash.get("video", []), dash.get("audio", [])
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
                    durl = data.get("durl", [])
                    if durl:
                        video_url, audio_url = durl[0].get("url", ""), None

                if not video_url:
                    return DownloadResult(success=False, error_code="NO_VIDEO_URL")

                output.parent.mkdir(parents=True, exist_ok=True)

                if audio_url:
                    vt, at = output.with_suffix(".video.mp4"), output.with_suffix(".audio.mp4")
                    await self._dl(client, video_url, vt, headers)
                    await self._dl(client, audio_url, at, headers)
                    cmd = ["ffmpeg", "-y", "-i", str(vt), "-i", str(at), "-c:v", "copy", "-c:a", "aac", str(output)]
                    proc = await asyncio.create_subprocess_exec(*cmd)
                    try:
                        await asyncio.wait_for(proc.communicate(), timeout=600)
                    except asyncio.TimeoutError:
                        proc.kill()
                    vt.unlink(missing_ok=True)
                    at.unlink(missing_ok=True)
                    if output.exists():
                        return DownloadResult(success=True, file_path=output, file_type="mp4")

                await self._dl(client, video_url, output, headers)
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
            resp = await client.get(f"{BILIBILI_API_BASE}/x/player/v2", params=params, headers=headers)
            if resp.status_code != 200:
                return ""
            for sub in resp.json().get("data", {}).get("subtitle", {}).get("subtitles", []):
                if language in sub.get("lan_doc", "") or sub.get("language") == language:
                    sub_url = sub.get("subtitle_url", "")
                    if sub_url:
                        if sub_url.startswith("//"):
                            sub_url = "https:" + sub_url
                        resp2 = await client.get(sub_url)
                        if resp2.status_code == 200:
                            lines = []
                            for s in resp2.json().get("body", []):
                                h, r = divmod(int(s.get("from", 0)), 3600)
                                m, s2 = divmod(r, 60)
                                lines.append(f"**{h:02d}:{m:02d}:{s2:02d} →** {s.get('content', '')}")
                            return "\n".join(lines)
            return ""

    async def get_metadata(self, item: ContentItem) -> dict:
        headers = self._build_headers()
        bvid = item.metadata.get("bvid", item.item_id)
        async with httpx.AsyncClient(timeout=10) as client:
            params = {"bvid": bvid} if bvid.startswith("BV") else {"avid": item.item_id}
            resp = await client.get(f"{BILIBILI_API_BASE}/x/web-interface/view", params=params, headers=headers)
            if resp.status_code == 200:
                d = resp.json().get("data", {})
                return {"title": d.get("title", ""), "desc": d.get("desc", ""), "duration": d.get("duration", 0)}
            return {"title": item.title}

    def _build_headers(self) -> dict:
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com",
        }
        if self._cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
        return h

    async def _dl(self, client: httpx.AsyncClient, url: str, output: Path, headers: dict):
        r = await client.get(url, headers=headers)
        if r.status_code == 200:
            output.write_bytes(r.content)

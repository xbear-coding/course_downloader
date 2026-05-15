"""B站平台插件 — 收藏夹 + UP主视频 + 字幕"""
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
            if r.status_code == 200:
                wi = r.json().get("data", {}).get("wbi_img", {})
                if wi:
                    _wbi_keys = {"img_key": wi.get("img_key", ""), "sub_key": wi.get("sub_key", "")}
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
    sp = urllib.parse.urlencode({k: signed[k] for k in keys})
    signed["w_rid"] = hashlib.md5((sp + mix_key).encode()).hexdigest()
    return signed


def _extract_mid(url_or_name: str) -> str | None:
    """从URL或名字中提取mid"""
    m = re.search(r'space\.bilibili\.com/(\d+)', url_or_name)
    if m:
        return m.group(1)
    return None


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
        """获取用户收藏夹视频列表"""
        headers = self._build_headers()
        mid = await self._get_mid()
        if not mid:
            return FetchResult(items=[], partial=True)

        await _update_wbi_keys(headers)
        page = int(page_token or 1)

        try:
            async with httpx.AsyncClient(timeout=15) as c:
                # 先获取收藏夹列表
                r = await c.get(
                    f"{BILIBILI_API_BASE}/x/v3/fav/folder/created/list",
                    params={"up_mid": mid}, headers=headers,
                )
                folders = r.json().get("data", {}).get("list", []) if r.status_code == 200 else []
                if not folders:
                    logger.warning("[bilibili] 无收藏夹")
                    return FetchResult(items=[], partial=True)

                # 取第一个收藏夹的视频
                media_id = folders[0].get("media_id") or folders[0].get("id", 0)
                r2 = await c.get(
                    f"{BILIBILI_API_BASE}/x/v3/fav/resource/list",
                    params={"media_id": media_id, "pn": page, "ps": 20},
                    headers=headers,
                )
                if r2.status_code != 200:
                    return FetchResult(items=[], partial=True)

                items = []
                for v in r2.json().get("data", {}).get("medias", []):
                    aid = str(v.get("id") or v.get("aid", ""))
                    bvid = v.get("bvid", "")
                    if not aid and not bvid:
                        continue
                    items.append(ContentItem(
                        platform="bilibili", item_id=bvid or aid,
                        title=v.get("title", "未知视频"), content_type="video",
                        url=f"https://www.bilibili.com/video/{bvid or aid}",
                        metadata={"bvid": bvid, "duration": v.get("duration", 0)},
                    ))

                info = r2.json().get("data", {}).get("info", {})
                total = info.get("media_count", 0)
                return FetchResult(items=items, total_estimated=total,
                                  next_token=str(page + 1) if page * 20 < total else None)
        except Exception as e:
            logger.error(f"[bilibili] 获取收藏失败: {e}")
            return FetchResult(items=[], partial=True)

    async def fetch_list_up(self, up_url_or_mid: str, page_token: Optional[str] = None) -> FetchResult:
        """获取指定UP主的视频列表"""
        headers = self._build_headers()
        mid = _extract_mid(up_url_or_mid) or up_url_or_mid
        await _update_wbi_keys(headers)

        page = int(page_token or 1)
        items = []
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                params = _sign_wbi({"mid": mid, "ps": 30, "pn": page})
                r = await c.get(f"{BILIBILI_API_BASE}/x/space/wbi/arc/search", params=params, headers=headers)
                if r.status_code != 200:
                    return FetchResult(items=[], partial=True)
                data = r.json().get("data", {})
                vlist = data.get("list", {}).get("vlist", []) or data.get("list", []) or []
                for v in vlist:
                    aid = str(v.get("aid") or v.get("bvid", ""))
                    if not aid:
                        continue
                    items.append(ContentItem(
                        platform="bilibili", item_id=aid, title=v.get("title", "未知视频"),
                        content_type="video",
                        url=f"https://www.bilibili.com/video/{v.get('bvid', aid)}",
                        metadata={"bvid": v.get("bvid", ""), "duration": v.get("duration", 0)},
                    ))
                total = data.get("page", {}).get("count", 0) or data.get("total", 0)
                return FetchResult(items=items, total_estimated=total,
                                  next_token=str(page + 1) if page * 30 < total else None)
        except Exception as e:
            logger.error(f"[bilibili] 获取UP主视频失败: {e}")
            return FetchResult(items=[], partial=True)

    async def download_video(self, item: ContentItem, output: Path, quality: str = "720p") -> DownloadResult:
        try:
            headers = self._build_headers()
            bvid = item.metadata.get("bvid", item.item_id)
            await _update_wbi_keys(headers)
            async with httpx.AsyncClient(timeout=30) as c:
                params = {"bvid": bvid, "qn": 80, "fnval": 4048} if bvid.startswith("BV") else {"avid": item.item_id, "qn": 80, "fnval": 4048}
                r = await c.get(f"{BILIBILI_API_BASE}/x/player/wbi/playurl", params=_sign_wbi(params), headers=headers)
                if r.status_code != 200:
                    return DownloadResult(success=False, error_code="API_FAIL", error_message=f"B站API返回{r.status_code}")
                data = r.json().get("data", {})
                dash = data.get("dash", {})
                video_url, audio_url = None, None
                if dash:
                    videos, audios = dash.get("video", []), dash.get("audio", [])
                    qn_map = {"360p": 32, "480p": 64, "720p": 80, "1080p": 120}
                    target_id = qn_map.get(quality, 80)
                    best = None
                    for v in videos:
                        if v.get("id", 0) <= target_id and (not best or v.get("id", 0) > best.get("id", 0)):
                            best = v
                    video_url = best.get("baseUrl", "") if best else ""
                    audio_url = audios[0].get("baseUrl", "") if audios else ""
                if not video_url:
                    durl = data.get("durl", [])
                    if durl:
                        video_url, audio_url = durl[0].get("url", ""), None
                if not video_url:
                    return DownloadResult(success=False, error_code="NO_VIDEO_URL")
                output.parent.mkdir(parents=True, exist_ok=True)
                if audio_url:
                    vt, at = output.with_suffix(".v.mp4"), output.with_suffix(".a.mp4")
                    await self._dl(c, video_url, vt, headers)
                    await self._dl(c, audio_url, at, headers)
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
                await self._dl(c, video_url, output, headers)
                if output.exists() and output.stat().st_size > 1024:
                    return DownloadResult(success=True, file_path=output, file_type="mp4")
                return DownloadResult(success=False, error_code="DOWNLOAD_FAILED")
        except Exception as e:
            return DownloadResult(success=False, error_code="ERROR", error_message=str(e)[:200])

    async def download_subtitle(self, item: ContentItem, language: str = "zh") -> str:
        headers = self._build_headers()
        bvid = item.metadata.get("bvid", item.item_id)
        async with httpx.AsyncClient(timeout=15) as c:
            params = {"bvid": bvid} if bvid.startswith("BV") else {"avid": item.item_id}
            r = await c.get(f"{BILIBILI_API_BASE}/x/player/v2", params=params, headers=headers)
            if r.status_code != 200:
                return ""
            for sub in r.json().get("data", {}).get("subtitle", {}).get("subtitles", []):
                if language in sub.get("lan_doc", "") or sub.get("language") == language:
                    su = sub.get("subtitle_url", "")
                    if su:
                        if su.startswith("//"):
                            su = "https:" + su
                        r2 = await c.get(su)
                        if r2.status_code == 200:
                            lines = []
                            for s in r2.json().get("body", []):
                                h, r = divmod(int(s.get("from", 0)), 3600)
                                m, s2 = divmod(r, 60)
                                lines.append(f"**{h:02d}:{m:02d}:{s2:02d} →** {s.get('content', '')}")
                            return "\n".join(lines)
            return ""

    async def get_metadata(self, item: ContentItem) -> dict:
        headers = self._build_headers()
        bvid = item.metadata.get("bvid", item.item_id)
        async with httpx.AsyncClient(timeout=10) as c:
            params = {"bvid": bvid} if bvid.startswith("BV") else {"avid": item.item_id}
            r = await c.get(f"{BILIBILI_API_BASE}/x/web-interface/view", params=params, headers=headers)
            if r.status_code == 200:
                d = r.json().get("data", {})
                return {"title": d.get("title", ""), "desc": d.get("desc", ""), "duration": d.get("duration", 0)}
            return {"title": item.title}

    async def _get_mid(self) -> str | None:
        headers = self._build_headers()
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{BILIBILI_API_BASE}/x/web-interface/nav", headers=headers)
                return str(r.json().get("data", {}).get("mid", 0)) if r.status_code == 200 else None
        except Exception:
            return None

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

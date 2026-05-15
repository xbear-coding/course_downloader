"""小鹅通平台插件（appid 自动发现 + 课程列表 + m3u8 下载）"""
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
from app.database import async_session

logger = logging.getLogger(__name__)

XIAOE_HOME = "https://www.xiaoe-tech.com"


def _extract_appid(url: str) -> str | None:
    m = re.search(r"app[a-zA-Z0-9]{14,24}", url)
    return m.group(0) if m else None


def _build_url(base_url: str, path: str = "") -> str:
    return f"{base_url}{path}"


async def _get_account_base_url(account_id: int) -> str | None:
    from app.models import Account
    async with async_session() as db:
        acct = await db.get(Account, account_id)
        if acct and acct.cookie_file and acct.cookie_file.startswith("xiaoe:"):
            return acct.cookie_file.split(":", 1)[1]
    return None


async def _save_account_base_url(account_id: int, base_url: str):
    from app.models import Account
    async with async_session() as db:
        acct = await db.get(Account, account_id)
        if acct:
            acct.cookie_file = f"xiaoe:{base_url}"
            await db.commit()


class XiaoEPlugin(BasePlatform, VideoCapable):
    """小鹅通插件

    流程：
    1. 登录 → 自动检测 base_url → 持久化
    2. 课程列表：访问课程页 → 点"加载更多"至全部 → 提取条目
    3. 下载：点击课程 → CDP 拦截 m3u8 → 下载合并 → ASR
    """

    def __init__(self):
        self.browser_mgr = BrowserManager()
        self._base_url: str | None = None

    @property
    def platform(self) -> str:
        return "xiaoe"

    async def _resolve_base_url(self, account_id: int) -> str | None:
        if self._base_url:
            return self._base_url
        self._base_url = await _get_account_base_url(account_id)
        return self._base_url

    async def _check_logged_in(self, page) -> bool:
        url = page.url
        if "login" not in url.lower() and "www.xiaoe-tech.com" not in url:
            return True
        try:
            body = await page.inner_text("body")
            if "退出" in body or "我的课程" in body or "我的学习" in body:
                return True
            user_els = await page.query_selector_all(
                '[class*=avatar], [class*=user], [class*=User], '
                '[class*=userInfo], [class*=nickname]'
            )
            if user_els:
                return True
        except Exception:
            pass
        return False

    async def login(self, account_id: int) -> LoginResult:
        try:
            existing_base = await self._resolve_base_url(account_id)
            start_url = existing_base or f"{XIAOE_HOME}/login"
            pb = await self.browser_mgr.get_browser(self.platform, headless=False)
            page = await pb.new_page()
            await page.goto(start_url, wait_until="domcontentloaded")
            await asyncio.sleep(3)
            if await self._check_logged_in(page):
                base = await page.evaluate("window.location.origin")
                if base and base != existing_base:
                    await _save_account_base_url(account_id, base)
                    self._base_url = base
                return LoginResult(success=True)
            for _ in range(180):
                await asyncio.sleep(1)
                if await self._check_logged_in(page):
                    base = await page.evaluate("window.location.origin")
                    if base:
                        await _save_account_base_url(account_id, base)
                        self._base_url = base
                    return LoginResult(success=True)
            return LoginResult(success=False, error_code="TIMEOUT", error_message="登录超时")
        except Exception as e:
            return LoginResult(success=False, error_code="ERROR", error_message=str(e)[:100])

    async def fetch_list(self, page_token: Optional[str] = None) -> FetchResult:
        from app.models import Account, Platform
        from sqlalchemy import select

        async with async_session() as db:
            platform = (await db.execute(select(Platform).where(Platform.name == "xiaoe"))).scalar_one_or_none()
            if not platform:
                return FetchResult(items=[], partial=True)
            acct = (await db.execute(
                select(Account).where(Account.platform_id == platform.id, Account.is_active == True)
            )).scalar_one_or_none()
            if not acct:
                return FetchResult(items=[], partial=True)
            base_url = await self._resolve_base_url(acct.id) or _extract_appid(acct.cookie_file or "")
            if not base_url:
                return FetchResult(items=[], partial=True)

        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        try:
            # 访问课程列表页（使用用户提供的完整页面 URL）
            course_url = f"{base_url}/p/t_pc/course_pc_detail/column/p_60f40504e4b08f7ad23e0e60"
            await page.goto(course_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(5)

            # 反复点击"加载更多"
            for _ in range(50):
                try:
                    btn = await page.query_selector(".load_more_btn, [class*=load_more]")
                    if not btn:
                        break
                    await btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.3)
                    visible = await btn.is_visible()
                    if not visible:
                        await page.evaluate("window.scrollBy(0, 300)")
                        await asyncio.sleep(0.5)
                        continue
                    await btn.click()
                    await asyncio.sleep(1)
                except Exception:
                    break

            await asyncio.sleep(2)

            # 提取课程条目
            items = []
            seen_titles = set()

            entries = await page.evaluate("""() => {
                const items = document.querySelectorAll(".item-title, [class*=item-title]");
                const result = [];
                items.forEach(el => {
                    const text = (el.textContent || "").trim();
                    if (text && text.length > 3) {
                        // Find parent for link
                        const parent = el.closest("a") || el.querySelector("a");
                        const href = parent ? (parent.getAttribute("href") || "") : "";
                        result.push({title: text, href: href});
                    }
                });
                return result;
            }""")

            for e in entries:
                title = e["title"].strip()
                # 去重（同一条目可能出现多次）
                if title in seen_titles:
                    continue
                if "上传练习" in title or len(title) < 5:
                    continue
                seen_titles.add(title)

                item_id = title.split("--")[0].strip() if "--" in title else title[:20]
                items.append(ContentItem(
                    platform="xiaoe",
                    item_id=item_id,
                    title=title[:200],
                    content_type="video",
                    url=e["href"] if e["href"].startswith("http") else f"{base_url}{e['href']}",
                ))

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
            url = response.url
            if ".m3u8" in url and ("xiaoe" in url or "cloud" in url):
                m3u8_url = url

        page.on("response", intercept_response)

        try:
            # 访问课程页面
            await page.goto(item.url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(5)

            # 尝试播放（点击播放按钮或视频区域）
            try:
                play_btn = await page.query_selector(
                    "button:has-text('播放'), .play-btn, [class*='play'], video, "
                    "[class*='video'], [class*='player']"
                )
                if play_btn:
                    await play_btn.click()
                    await asyncio.sleep(3)
            except Exception:
                pass

            # 等待 m3u8 请求
            for _ in range(30):
                if m3u8_url:
                    break
                await asyncio.sleep(1)

            if m3u8_url:
                return await self._download_m3u8(m3u8_url, output)

            # 回退：尝试从 video 标签获取
            video_src = await page.evaluate("""() => {
                const v = document.querySelector('video');
                return v ? (v.src || (v.querySelector('source')?.src) || '') : '';
            }""")
            if video_src:
                import httpx
                async with httpx.AsyncClient(timeout=300) as c:
                    r = await c.get(video_src)
                    if r.status_code == 200:
                        output.write_bytes(r.content)
                        return DownloadResult(success=True, file_path=output, file_type="ts")

            return DownloadResult(success=False, error_code="NO_M3U8", error_message="未捕获到视频流")
        except Exception as e:
            return DownloadResult(success=False, error_code="ERROR", error_message=str(e)[:200])
        finally:
            page.remove_listener("response", intercept_response)
            await page.close()

    async def _download_m3u8(self, m3u8_url: str, output: Path) -> DownloadResult:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(m3u8_url)
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
                        ts_url = line if line.startswith("http") else base + line
                        ts_urls.append(ts_url)

                if not ts_urls:
                    return DownloadResult(success=False, error_code="NO_TS")

                output.parent.mkdir(parents=True, exist_ok=True)
                with open(output, "wb") as f:
                    for i, ts_url in enumerate(ts_urls):
                        try:
                            r = await client.get(ts_url, timeout=30)
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

"""小红书平台插件"""
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional
import httpx
from app.services.platform_base import (
    BasePlatform, ArticleCapable, VideoCapable,
    LoginResult, ContentItem, FetchResult, DownloadResult,
)
from app.services.browser_manager import BrowserManager

logger = logging.getLogger(__name__)


class XiaohongshuPlugin(BasePlatform, ArticleCapable, VideoCapable):
    """小红书插件

    流程：
    1. 登录：扫码/手机号登录
    2. 列表：收藏夹/笔记列表
    3. 下载：图文笔记抓取（Markdown + 图片），视频下载
    """

    XHS_URL = "https://www.xiaohongshu.com"

    def __init__(self):
        self.browser_mgr = BrowserManager()

    @property
    def platform(self) -> str:
        return "xiaohongshu"

    async def login(self, account_id: int) -> LoginResult:
        try:
            pb = await self.browser_mgr.get_browser(self.platform, headless=False)
            page = await pb.new_page()
            await page.goto(f"{self.XHS_URL}/login", wait_until="domcontentloaded")

            await asyncio.sleep(2)
            if "login" not in page.url.lower():
                return LoginResult(success=True)

            # 等待扫码/手机登录（最长 180 秒）
            for _ in range(180):
                await asyncio.sleep(1)
                current = page.url
                if "login" not in current.lower() and "explore" in current.lower():
                    return LoginResult(success=True)
                try:
                    # 检测登录后页面特征
                    if await page.query_selector(".feeds-page, [class*='feed'], [class*='home']"):
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
            # 访问用户主页/收藏夹
            await page.goto(f"{self.XHS_URL}/explore", wait_until="networkidle")
            await asyncio.sleep(3)

            items = []
            prev_count = -1
            stable_rounds = 0

            for _ in range(10):
                cards = await page.query_selector_all(
                    ".note-item, [class*='note'], [class*='card'], a[href*='/explore/']"
                )
                current_count = len([c for c in cards if c])

                if current_count == prev_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                prev_count = current_count

                if stable_rounds >= 2:
                    break

                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.5)

            # 提取笔记链接
            seen = set()
            for card in cards:
                try:
                    href = await card.get_attribute("href") or ""
                    if "/explore/" not in href and "/discovery/" not in href:
                        continue

                    note_id = href.split("/")[-1].split("?")[0]
                    if not note_id or note_id in seen:
                        continue
                    seen.add(note_id)

                    # 提取标题
                    title_el = await card.query_selector(
                        ".title, [class*='title'], .desc, [class*='desc']"
                    )
                    title = await title_el.inner_text() if title_el else f"笔记 {note_id[:8]}"
                    title = title.strip()[:100]

                    # 判断类型（是否有视频标识）
                    is_video = await card.query_selector(
                        ".video-icon, [class*='video'], [class*='play']"
                    )

                    items.append(ContentItem(
                        platform="xiaohongshu",
                        item_id=note_id,
                        title=title,
                        content_type="video" if is_video else "article",
                        url=f"{self.XHS_URL}/explore/{note_id}",
                    ))
                except Exception as e:
                    logger.warning(f"[xiaohongshu] 解析卡片失败: {e}")
                    continue

            return FetchResult(items=items, total_estimated=len(items))

        except Exception as e:
            logger.error(f"[xiaohongshu] 获取列表失败: {e}")
            return FetchResult(items=[], partial=True)
        finally:
            await page.close()

    async def download_article(
        self, item: ContentItem, output: Path
    ) -> DownloadResult:
        pb = await self.browser_mgr.get_browser(self.platform, headless=False)
        page = await pb.new_page()

        try:
            await page.goto(item.url, wait_until="networkidle")
            await asyncio.sleep(3)

            # 提取标题
            title = item.title
            try:
                title_el = await page.query_selector(
                    ".title, [class*='title'], #title, h1"
                )
                if title_el:
                    title = (await title_el.inner_text()).strip()
            except Exception:
                pass

            # 提取正文
            content_lines = [f"# {title}\n"]
            try:
                desc_el = await page.query_selector(
                    ".desc, [class*='desc'], .content, [class*='content'], article"
                )
                if desc_el:
                    desc = (await desc_el.inner_text()).strip()
                    content_lines.append(desc)
            except Exception:
                pass

            # 提取图片
            image_dir = output.parent / f"{item.item_id}_images"
            image_dir.mkdir(parents=True, exist_ok=True)

            image_urls = []
            try:
                imgs = await page.query_selector_all(
                    ".carousel img, [class*='slide'] img, .note-img img, "
                    ".swiper img, [class*='image'] img, img[src*='xhscdn']"
                )
                for img in imgs:
                    src = await img.get_attribute("src") or ""
                    if src and src.startswith("http") and src not in image_urls:
                        image_urls.append(src)
            except Exception:
                pass

            # 下载图片
            if image_urls:
                content_lines.append("\n## 图片\n")
                async with httpx.AsyncClient(timeout=30) as client:
                    for i, img_url in enumerate(image_urls):
                        try:
                            resp = await client.get(img_url)
                            if resp.status_code == 200:
                                ext = img_url.split("?")[0].rsplit(".", 1)[-1][:4] or "jpg"
                                img_path = image_dir / f"{i + 1}.{ext}"
                                img_path.write_bytes(resp.content)
                                content_lines.append(f"![图片{i+1}](images/{img_path.name})")
                        except Exception as e:
                            logger.warning(f"[xiaohongshu] 图片 {i} 下载失败: {e}")
                            continue

            # 写入文件
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("\n\n".join(content_lines), encoding="utf-8")

            if output.exists():
                return DownloadResult(success=True, file_path=output, file_type="md")
            return DownloadResult(success=False, error_code="WRITE_FAILED")

        except Exception as e:
            return DownloadResult(success=False, error_code="ERROR", error_message=str(e)[:200])
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

            # 尝试从 video 标签获取源
            video_url = None
            try:
                video_url = await page.evaluate("""() => {
                    const v = document.querySelector('video');
                    if (!v) return null;
                    return v.src || v.querySelector('source')?.src || null;
                }""")
            except Exception:
                pass

            if video_url and video_url.startswith("http"):
                import httpx
                async with httpx.AsyncClient(timeout=300) as client:
                    resp = await client.get(video_url)
                    if resp.status_code == 200:
                        output.write_bytes(resp.content)
                        return DownloadResult(success=True, file_path=output, file_type="mp4")

            return DownloadResult(success=False, error_code="NO_VIDEO_SRC")
        except Exception as e:
            return DownloadResult(success=False, error_code="ERROR", error_message=str(e)[:200])
        finally:
            await page.close()

    async def get_metadata(self, item: ContentItem) -> dict:
        return {"title": item.title, "platform": "xiaohongshu"}

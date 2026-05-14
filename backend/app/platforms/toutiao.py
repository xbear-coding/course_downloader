"""今日头条平台插件"""
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


class ToutiaoPlugin(BasePlatform, ArticleCapable, VideoCapable):
    """今日头条插件

    流程：
    1. 登录：扫码/手机号登录
    2. 列表：收藏/关注列表
    3. 下载：图文抓取（Markdown），视频下载
    """

    TOUTIAO_URL = "https://www.toutiao.com"

    def __init__(self):
        self.browser_mgr = BrowserManager()

    @property
    def platform(self) -> str:
        return "toutiao"

    async def login(self, account_id: int) -> LoginResult:
        try:
            pb = await self.browser_mgr.get_browser(self.platform, headless=False)
            page = await pb.new_page()
            await page.goto(f"{self.TOUTIAO_URL}/", wait_until="domcontentloaded")

            await asyncio.sleep(2)

            # 检测是否已登录
            try:
                has_login = await page.evaluate("""() => {
                    const el = document.querySelector('.user-info, [class*="avatar"], [class*="login-btn"]');
                    if (el) {
                        const text = el.textContent || '';
                        return !(text.includes('登录') || text.includes('注册'));
                    }
                    return !!document.querySelector('[class*="user"]');
                }""")
                if has_login:
                    return LoginResult(success=True)
            except Exception:
                pass

            # 点击登录按钮打开登录弹窗
            try:
                login_btn = await page.query_selector(
                    ".login-button, [class*='login'], button:has-text('登录')"
                )
                if login_btn:
                    await login_btn.click()
                    await asyncio.sleep(2)
            except Exception:
                pass

            # 等待扫码/手机登录（最长 180 秒）
            for _ in range(180):
                await asyncio.sleep(1)
                try:
                    has_login = await page.evaluate("""() => {
                        return !!(document.querySelector('[class*="user"]')
                            || document.querySelector('.user-info'));
                    }""")
                    if has_login:
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
            await page.goto(f"{self.TOUTIAO_URL}/", wait_until="networkidle")
            await asyncio.sleep(3)

            items = []
            prev_count = -1
            stable_rounds = 0

            for _ in range(10):
                cards = await page.query_selector_all(
                    ".feed-card, [class*='feed'], [class*='card'], "
                    "article, .article-item, a[href*='article']"
                )
                current_count = len(cards)

                if current_count == prev_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                prev_count = current_count

                if stable_rounds >= 2:
                    break

                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.5)

            seen = set()
            for card in cards:
                try:
                    link_el = await card.query_selector("a[href]")
                    href = await link_el.get_attribute("href") if link_el else ""
                    if not href:
                        continue

                    # 标准化 URL
                    if href.startswith("//"):
                        href = "https:" + href
                    elif href.startswith("/"):
                        href = self.TOUTIAO_URL + href

                    # 提取文章/视频 ID
                    item_id = ""
                    m = re.search(r'/(\d{15,})', href)
                    if m:
                        item_id = m.group(1)
                    if not item_id and "/video/" in href:
                        m = re.search(r'/video/(\d+)', href)
                        if m:
                            item_id = m.group(1)

                    if not item_id or item_id in seen:
                        continue
                    seen.add(item_id)

                    # 提取标题
                    title_el = await card.query_selector(
                        ".title, [class*='title'], h2, h3, h4"
                    )
                    title = await title_el.inner_text() if title_el else f"内容 {item_id[:8]}"
                    title = title.strip()[:100]

                    # 判断类型
                    is_video = await card.query_selector(
                        ".video-icon, [class*='video'], [class*='play']"
                    ) or "/video/" in href

                    items.append(ContentItem(
                        platform="toutiao",
                        item_id=item_id,
                        title=title,
                        content_type="video" if is_video else "article",
                        url=href,
                    ))
                except Exception as e:
                    logger.warning(f"[toutiao] 解析卡片失败: {e}")
                    continue

            return FetchResult(items=items, total_estimated=len(items))

        except Exception as e:
            logger.error(f"[toutiao] 获取列表失败: {e}")
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

            # 提取文章内容
            title = item.title
            try:
                title_el = await page.query_selector(
                    ".article-title, h1, .title"
                )
                if title_el:
                    title = (await title_el.inner_text()).strip()
            except Exception:
                pass

            content_lines = [f"# {title}\n"]

            # 提取正文
            try:
                article_el = await page.query_selector(
                    ".article-content, [class*='content'], article, "
                    ".rich-content, .article-detail"
                )
                if article_el:
                    paragraphs = await article_el.query_selector_all("p")
                    for p in paragraphs:
                        text = (await p.inner_text()).strip()
                        if text:
                            content_lines.append(text)
            except Exception:
                pass

            # 提取并下载图片
            image_dir = output.parent / f"{item.item_id}_images"
            image_dir.mkdir(parents=True, exist_ok=True)

            image_urls = []
            try:
                imgs = await page.query_selector_all(
                    ".article-content img, [class*='content'] img, "
                    ".article-detail img, img[src*='toutiao']"
                )
                for img in imgs:
                    src = await img.get_attribute("src") or ""
                    if src.startswith("http") and src not in image_urls:
                        image_urls.append(src)
            except Exception:
                pass

            if image_urls:
                content_lines.append("\n## 图片\n")
                async with httpx.AsyncClient(timeout=30) as client:
                    for i, img_url in enumerate(image_urls):
                        try:
                            resp = await client.get(img_url)
                            if resp.status_code == 200:
                                img_path = image_dir / f"{i + 1}.jpg"
                                img_path.write_bytes(resp.content)
                                content_lines.append(f"![图片{i+1}](images/{img_path.name})")
                        except Exception:
                            continue

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
            video_url = await page.evaluate("""() => {
                const v = document.querySelector('video');
                if (!v) return null;
                return v.src || (v.querySelector('source')?.src) || null;
            }""")

            if video_url and video_url.startswith("http"):
                async with httpx.AsyncClient(timeout=300) as client:
                    resp = await client.get(video_url, follow_redirects=True)
                    if resp.status_code == 200 and len(resp.content) > 1024:
                        output.write_bytes(resp.content)
                        return DownloadResult(success=True, file_path=output, file_type="mp4")

            # 尝试从页面数据中提取
            video_info = await page.evaluate("""() => {
                try {
                    const scripts = document.querySelectorAll('script');
                    for (const s of scripts) {
                        if (s.textContent.includes('video_url')) {
                            const m = s.textContent.match(/video_url["': ]+["']([^"']+)["']/);
                            if (m) return m[1];
                        }
                        if (s.textContent.includes('videoUrl')) {
                            const m = s.textContent.match(/videoUrl["': ]+["']([^"']+)["']/);
                            if (m) return m[1];
                        }
                    }
                } catch(e) {}
                return null;
            }""")

            if video_info:
                async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
                    resp = await client.get(video_info)
                    if resp.status_code == 200 and len(resp.content) > 1024:
                        output.write_bytes(resp.content)
                        return DownloadResult(success=True, file_path=output, file_type="mp4")

            return DownloadResult(success=False, error_code="NO_VIDEO_SRC")
        except Exception as e:
            return DownloadResult(success=False, error_code="ERROR", error_message=str(e)[:200])
        finally:
            await page.close()

    async def get_metadata(self, item: ContentItem) -> dict:
        return {"title": item.title, "platform": "toutiao"}

"""E2E 浏览器测试 — 前端渲染 + API 交互"""
import pytest


class TestFrontendPages:
    """前端页面加载测试"""

    async def test_frontend_homepage(self):
        """验证前端首页能正常加载（需要 frontend dev server 运行）"""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get("http://localhost:5173")
                assert r.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            pytest.skip("前端服务器未运行")

    async def test_frontend_dashboard(self):
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get("http://localhost:5173/")
                assert r.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            pytest.skip("前端服务器未运行")


class TestBackendAPI:
    """后端 API 完整流程测试"""

    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"

    async def test_full_lifecycle(self, client):
        """完整 CRUD 生命周期测试"""
        # 1. 创建平台
        r = await client.post("/api/platforms", json={
            "name": "test_platform", "display_name": "测试平台",
        })
        assert r.status_code == 201
        plat_id = r.json()["id"]

        # 2. 获取平台
        r = await client.get(f"/api/platforms/{plat_id}")
        assert r.status_code == 200
        assert r.json()["name"] == "test_platform"

        # 3. 更新平台
        r = await client.patch(f"/api/platforms/{plat_id}", json={"output_dir": "/tmp/test"})
        assert r.status_code == 200
        assert r.json()["output_dir"] == "/tmp/test"

        # 4. 创建账号
        r = await client.post(f"/api/platforms/{plat_id}/accounts", json={
            "platform_id": plat_id, "name": "测试账号",
        })
        assert r.status_code == 201
        acct_id = r.json()["id"]

        # 5. 创建任务
        r = await client.post("/api/tasks", json={
            "platform": "test_platform",
            "resource_id": "e2e_001",
            "title": "E2E测试任务",
            "content_type": "video",
        })
        assert r.status_code == 201
        task_id = r.json()["id"]

        # 6. 查询任务
        r = await client.get(f"/api/tasks/{task_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "pending"

        # 7. 筛选任务
        r = await client.get("/api/tasks?status=pending")
        assert r.status_code == 200
        assert len(r.json()["data"]) >= 1

        # 8. 重试任务
        r = await client.post(f"/api/tasks/{task_id}/retry")
        assert r.status_code == 200

        # 9. 删除任务
        r = await client.delete(f"/api/tasks/{task_id}")
        assert r.status_code == 204

        # 10. 删除账号
        r = await client.delete(f"/api/platforms/{plat_id}")
        assert r.status_code == 204


class TestPluginRegistry:
    """平台插件注册表测试"""

    async def test_all_plugins_registered(self):
        from app.platforms import list_platforms, get_platform
        platforms = list_platforms()
        assert len(platforms) >= 6
        for name in platforms:
            p = get_platform(name)
            assert p is not None
            assert p.platform == name

    async def test_plugin_singleton(self):
        """验证 get_platform 返回同一实例"""
        from app.platforms import get_platform
        p1 = get_platform("tencent_meeting")
        p2 = get_platform("tencent_meeting")
        assert p1 is p2  # 同一实例

    async def test_plugin_reset(self):
        """验证 reset_platform 清除实例"""
        from app.platforms import get_platform, reset_platform
        p1 = get_platform("tencent_meeting")
        reset_platform("tencent_meeting")
        p2 = get_platform("tencent_meeting")
        assert p1 is not p2  # 不同实例


class TestMediaConverter:
    """媒体转码测试"""

    async def test_ffmpeg_available(self):
        import asyncio
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-version",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        assert proc.returncode == 0
        assert b"ffmpeg" in stdout

    async def test_extract_audio_ts(self):
        """测试从 TS 文件提取音频"""
        from app.services.media_converter import extract_audio
        from pathlib import Path
        import tempfile

        # 创建一个最小的有效 TS 文件用于测试
        ts_file = Path(tempfile.gettempdir()) / "test_minimal.ts"
        wav_file = ts_file.with_suffix(".wav")

        # 用 ffmpeg 生成 1 秒的测试 TS
        import asyncio
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", "1", str(ts_file),
        ]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.communicate()

        if not ts_file.exists():
            pytest.skip("ffmpeg 无法生成测试文件")

        result = await extract_audio(ts_file, wav_file, sample_rate=16000)
        assert result is True
        assert wav_file.exists()
        assert wav_file.stat().st_size > 100

        wav_file.unlink(missing_ok=True)
        ts_file.unlink(missing_ok=True)


class TestBrowserManager:
    """浏览器管理器测试"""

    async def test_singleton(self):
        from app.services.browser_manager import BrowserManager
        b1 = BrowserManager()
        b2 = BrowserManager()
        assert b1 is b2

    async def test_active_count(self):
        from app.services.browser_manager import BrowserManager
        bm = BrowserManager()
        assert bm.active_count >= 0

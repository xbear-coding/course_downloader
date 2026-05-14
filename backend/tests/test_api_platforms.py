"""测试平台 API endpoints"""
import pytest


class TestListPlatforms:
    """GET /api/platforms"""

    async def test_empty(self, client):
        resp = await client.get("/api/platforms")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_with_seed_data(self, seeded_client):
        resp = await seeded_client.get("/api/platforms")
        data = resp.json()
        assert len(data) == 6
        names = [p["name"] for p in data]
        assert "tencent_meeting" in names
        assert "xiaoe" in names
        assert "bilibili" in names
        # 验证排序
        sort_orders = [p["sort_order"] for p in data]
        assert sort_orders == sorted(sort_orders)

    async def test_response_shape(self, seeded_client):
        resp = await seeded_client.get("/api/platforms")
        platform = resp.json()[0]
        assert "id" in platform
        assert "name" in platform
        assert "display_name" in platform
        assert "enabled" in platform
        assert "output_dir" in platform
        assert "sort_order" in platform
        assert "created_at" in platform


class TestCreatePlatform:
    """POST /api/platforms"""

    async def test_create(self, client):
        resp = await client.post("/api/platforms", json={
            "name": "new_platform",
            "display_name": "新平台",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "new_platform"
        assert data["display_name"] == "新平台"
        assert data["enabled"] is True

    async def test_duplicate_name(self, seeded_client):
        resp = await seeded_client.post("/api/platforms", json={
            "name": "tencent_meeting",
            "display_name": "重复",
        })
        # 数据库 UNIQUE 约束 → 409 Conflict
        assert resp.status_code == 409

    async def test_invalid_name_pattern(self, client):
        resp = await client.post("/api/platforms", json={
            "name": "Invalid Name!",
            "display_name": "测试",
        })
        assert resp.status_code == 422


class TestGetPlatform:
    """GET /api/platforms/{id}"""

    async def test_get_existing(self, seeded_client):
        resp = await seeded_client.get("/api/platforms/1")
        assert resp.status_code == 200
        assert resp.json()["id"] == 1

    async def test_get_not_found(self, client):
        resp = await client.get("/api/platforms/999")
        assert resp.status_code == 404


class TestUpdatePlatform:
    """PATCH /api/platforms/{id}"""

    async def test_update_output_dir(self, seeded_client):
        resp = await seeded_client.patch("/api/platforms/1", json={
            "output_dir": "/data/output",
        })
        assert resp.status_code == 200
        assert resp.json()["output_dir"] == "/data/output"

    async def test_update_not_found(self, client):
        resp = await client.patch("/api/platforms/999", json={"output_dir": "/tmp"})
        assert resp.status_code == 404


class TestDeletePlatform:
    """DELETE /api/platforms/{id}"""

    async def test_delete_existing(self, seeded_client):
        resp = await seeded_client.delete("/api/platforms/1")
        assert resp.status_code == 204

    async def test_delete_not_found(self, client):
        resp = await client.delete("/api/platforms/999")
        assert resp.status_code == 404


class TestAccountEndpoints:
    """测试平台下的账号管理"""

    async def test_list_accounts_empty(self, seeded_client):
        resp = await seeded_client.get("/api/platforms/1/accounts")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_account(self, seeded_client):
        resp = await seeded_client.post("/api/platforms/1/accounts", json={
            "platform_id": 1,
            "name": "熊子熠",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "熊子熠"
        assert data["platform_id"] == 1
        assert data["is_active"] is False

    async def test_list_accounts_after_create(self, seeded_client):
        await seeded_client.post("/api/platforms/1/accounts", json={
            "platform_id": 1, "name": "账号A",
        })
        await seeded_client.post("/api/platforms/1/accounts", json={
            "platform_id": 1, "name": "账号B",
        })
        resp = await seeded_client.get("/api/platforms/1/accounts")
        data = resp.json()
        assert len(data) == 2

    async def test_account_isolation(self, seeded_client):
        """不同平台的账号互不干扰"""
        await seeded_client.post("/api/platforms/1/accounts", json={
            "platform_id": 1, "name": "腾讯账号",
        })
        await seeded_client.post("/api/platforms/2/accounts", json={
            "platform_id": 2, "name": "小鹅通账号",
        })
        r1 = await seeded_client.get("/api/platforms/1/accounts")
        r2 = await seeded_client.get("/api/platforms/2/accounts")
        assert len(r1.json()) == 1
        assert len(r2.json()) == 1
        assert r1.json()[0]["name"] == "腾讯账号"
        assert r2.json()[0]["name"] == "小鹅通账号"

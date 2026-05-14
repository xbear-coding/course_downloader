"""测试 API Key endpoints"""


class TestListKeys:
    """GET /api/keys"""

    async def test_empty(self, client):
        resp = await client.get("/api/keys")
        assert resp.status_code == 200
        assert resp.json() == []


class TestCreateKey:
    """POST /api/keys"""

    async def test_create(self, client):
        resp = await client.post("/api/keys", json={
            "name": "测试Key",
            "key_value": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "provider": "siliconflow",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "测试Key"
        assert data["provider"] == "siliconflow"
        # Key 值应该脱敏显示
        assert "..." in data["key_value"]
        assert "xxxxxxxx" not in data["key_value"]

    async def test_default_provider(self, client):
        resp = await client.post("/api/keys", json={
            "name": "默认Provider",
            "key_value": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        })
        assert resp.json()["provider"] == "siliconflow"

    async def test_key_value_masked_in_list(self, client):
        await client.post("/api/keys", json={
            "name": "隐秘Key",
            "key_value": "sk-secret-key-value-12345678",
        })
        resp = await client.get("/api/keys")
        key = resp.json()[0]
        assert "secret" not in key["key_value"]
        assert key["key_value"].startswith("sk-")

    async def test_key_too_short_rejected(self, client):
        """短 Key（<10字符）应该被 schema 拒绝"""
        resp = await client.post("/api/keys", json={
            "name": "短Key",
            "key_value": "short",
        })
        assert resp.status_code == 422


class TestDeleteKey:
    """DELETE /api/keys/{id}"""

    async def test_delete_existing(self, client):
        create = await client.post("/api/keys", json={
            "name": "待删除",
            "key_value": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        })
        key_id = create.json()["id"]
        resp = await client.delete(f"/api/keys/{key_id}")
        assert resp.status_code == 204

    async def test_delete_not_found(self, client):
        resp = await client.delete("/api/keys/999")
        assert resp.status_code == 404


class TestTestKey:
    """POST /api/keys/{id}/test"""

    async def test_test_nonexistent(self, client):
        resp = await client.post("/api/keys/999/test")
        assert resp.status_code == 404

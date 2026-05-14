"""测试任务 API endpoints"""


class TestListTasks:
    """GET /api/tasks"""

    async def test_empty(self, client):
        resp = await client.get("/api/tasks")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == []
        assert body["pagination"]["total_items"] == 0
        assert body["pagination"]["total_pages"] == 0

    async def test_response_shape(self, client):
        resp = await client.get("/api/tasks")
        body = resp.json()
        assert "data" in body
        assert "pagination" in body
        assert "page" in body["pagination"]
        assert "page_size" in body["pagination"]
        assert "total_items" in body["pagination"]
        assert "total_pages" in body["pagination"]


class TestCreateTask:
    """POST /api/tasks"""

    async def test_create_video_task(self, client):
        resp = await client.post("/api/tasks", json={
            "platform": "tencent_meeting",
            "resource_id": "rec_001",
            "title": "测试录制",
            "content_type": "video",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "测试录制"
        assert data["platform"] == "tencent_meeting"
        assert data["status"] == "pending"
        assert data["content_type"] == "video"

    async def test_create_article_task(self, client):
        resp = await client.post("/api/tasks", json={
            "platform": "toutiao",
            "resource_id": "art_001",
            "title": "测试文章",
            "content_type": "article",
        })
        assert resp.status_code == 201
        assert resp.json()["content_type"] == "article"

    async def test_default_content_type(self, client):
        """不指定 content_type 应该默认为 video"""
        resp = await client.post("/api/tasks", json={
            "platform": "tencent_meeting",
            "resource_id": "rec_002",
            "title": "默认类型",
        })
        assert resp.status_code == 201
        assert resp.json()["content_type"] == "video"

    async def test_invalid_platform(self, client):
        """即使平台名无效也能创建（API 层不校验平台存在性）"""
        resp = await client.post("/api/tasks", json={
            "platform": "non_existent_platform",
            "resource_id": "x",
            "title": "测试",
        })
        assert resp.status_code == 201


class TestGetTask:
    """GET /api/tasks/{id}"""

    async def test_get_existing(self, client):
        create = await client.post("/api/tasks", json={
            "platform": "test", "resource_id": "x", "title": "测试",
        })
        task_id = create.json()["id"]
        resp = await client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == task_id

    async def test_get_not_found(self, client):
        resp = await client.get("/api/tasks/999")
        assert resp.status_code == 404


class TestDeleteTask:
    """DELETE /api/tasks/{id}"""

    async def test_delete_existing(self, client):
        create = await client.post("/api/tasks", json={
            "platform": "test", "resource_id": "x", "title": "测试",
        })
        task_id = create.json()["id"]
        resp = await client.delete(f"/api/tasks/{task_id}")
        assert resp.status_code == 204

    async def test_delete_not_found(self, client):
        resp = await client.delete("/api/tasks/999")
        assert resp.status_code == 404


class TestRetryTask:
    """POST /api/tasks/{id}/retry"""

    async def test_retry_resets_status(self, client):
        create = await client.post("/api/tasks", json={
            "platform": "test", "resource_id": "x", "title": "测试",
        })
        task_id = create.json()["id"]

        resp = await client.post(f"/api/tasks/{task_id}/retry")
        assert resp.status_code == 200
        assert resp.json()["message"] == "任务已重置为待重试"

    async def test_retry_not_found(self, client):
        resp = await client.post("/api/tasks/999/retry")
        assert resp.status_code == 404


class TestFilterAndPagination:
    """筛选和分页"""

    async def test_filter_by_platform(self, client):
        await client.post("/api/tasks", json={
            "platform": "tencent_meeting", "resource_id": "a", "title": "A",
        })
        await client.post("/api/tasks", json={
            "platform": "xiaoe", "resource_id": "b", "title": "B",
        })

        resp = await client.get("/api/tasks?platform=tencent_meeting")
        data = resp.json()["data"]
        assert all(t["platform"] == "tencent_meeting" for t in data)

    async def test_filter_by_status(self, client):
        await client.post("/api/tasks", json={
            "platform": "test", "resource_id": "a", "title": "A",
        })

        resp = await client.get("/api/tasks?status=pending")
        data = resp.json()["data"]
        assert all(t["status"] == "pending" for t in data)

    async def test_page_size(self, client):
        for i in range(5):
            await client.post("/api/tasks", json={
                "platform": "test", "resource_id": str(i), "title": f"Task {i}",
            })

        resp = await client.get("/api/tasks?page_size=2")
        body = resp.json()
        assert len(body["data"]) == 2
        assert body["pagination"]["page_size"] == 2
        assert body["pagination"]["total_items"] == 5
        assert body["pagination"]["total_pages"] == 3

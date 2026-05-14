# Course_Downloader — 架构修订与 Phase 1 实施计划

> 版本：v1.0 | 日期：2026-05-14
> 基于 75 个技能的全流程审查结果修订

---

## 第一章：架构修订清单

### 1.1 从审查中发现的所有修订项

| # | 问题 | 严重程度 | 修订内容 |
|---|------|---------|---------|
| R1 | ASR 模型指定错误 | 🔴 高 | 模型从 `SenseVoiceSmall` 改为 `TeleAI/TeleSpeechASR`（已验证支持时间戳输出） |
| R2 | 排队策略 | 🟡 中 | 从「全局排队」改为「平台内串行、平台间最多 2 个并发」 |
| R3 | 任务状态缺少 `partial` | 🔴 高 | 新增 `PARTIAL` 状态：视频成功但转写失败的中间态 |
| R4 | Phase 顺序不合理 | 🟡 中 | 小鹅通提前到 Phase 3，抖音推迟到 Phase 5 |
| R5 | API Key 加密方案过度设计 | 🟡 中 | 改为明文存储 + 日志脱敏，不做 AES-256 |
| R6 | REST API 路径不一致 | 🟡 中 | `/api/download/*` 改为 `/api/tasks`；`/api/api_keys` 改为 `/api/keys` |
| R7 | Playwright 实例内存估算偏差 | 🟡 中 | 实测 687MB/实例，限制最大 2 个实例 |
| R8 | 错误处理策略完全缺失 | 🔴 高 | 补充三层兜底错误处理方案 |
| R9 | XSS 防护 | 🟡 中 | 架构中明确「禁止 v-html，必须用 DOMPurify」 |
| R10 | .gitignore 未定义 | 🟡 中 | Phase 1 必须创建 |
| R11 | CORS + 安全头 + 全局异常处理 | 🟡 中 | Phase 1 必须配置 |
| R12 | 数据库字段用 Enum 而非 TEXT | 🟢 低 | status 字段用 SQLAlchemy Enum |
| R13 | BasePlatform 接口过多 | 🟡 中 | 拆分为 Mixin（VideoCapable / ArticleCapable / SubtitleCapable） |
| R14 | ContentItem 缺少类型区分 | 🟡 中 | 加 `content_type` 和 `metadata` 字段 |
| R15 | fetch_list 无分页机制 | 🟡 中 | 加 PageToken 游标 |

### 1.2 修订后的实施顺序

```
Phase 1: 项目骨架（14→20 tasks）
Phase 2: 腾讯会议（已验证基础可行性）
Phase 3: 小鹅通（现有代码直接迁移）
Phase 4: B站 + 今日头条（有公开API，中等难度）
Phase 5: 抖音（先验证火山引擎API可行性）
Phase 6: 小红书（最高难度，放最后）
Phase 7: 打磨（错误处理全覆盖、批量重试、磁盘监控）

Phase 1 内包含：「抖音可行性验证冲刺」1天
                  火山引擎是否有Douyin API？
                  如果没有，Playwright能否正常访问网页版收藏列表？
```

---

## 第二章：Phase 1 实施计划（20 个原子任务）

### Task 1：项目目录 + 环境配置

**文件：**
- `backend/requirements.txt`
- `backend/.env.example`
- `backend/app/__init__.py`
- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/database.py`

**requirements.txt：**
```
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy[asyncio]==2.0.35
aiosqlite==0.20.0
alembic==1.13.0
playwright==1.58.0
httpx==0.27.0
python-multipart==0.0.9
python-dotenv==1.0.0
```

**main.py：**
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="Course_Downloader", version="0.1.0")

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(Exception)
async def global_handler(request, exc):
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL", "message": "An unexpected error occurred"}})

@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
```

**验证：**
```bash
cd backend && pip install -r requirements.txt
uvicorn app.main:app --port 8000 &
curl -s http://localhost:8000/health
# 预期：{"status":"ok","version":"0.1.0"}
kill %1
```

---

### Task 2：数据库模型 + Alembic 迁移

**models.py 包含 4 张表：platforms / accounts / tasks / api_keys**

**验收标准：**
- `alembic upgrade head` 成功执行
- SQLite 文件创建在 `data/course_downloader.db`

```python
import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Enum
from sqlalchemy.orm import DeclarativeBase
from datetime import datetime

class Base(DeclarativeBase):
    pass

class TaskStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PARTIAL = "partial"
    DONE = "done"
    FAILED = "fail"
    CANCELLED = "cancelled"
    FATAL = "fatal"
    UPDATED = "updated"
    NEW = "new"
```

（完整 4 张表的字段定义见数据库结构文档）

**验证：**
```bash
alembic upgrade head
python -c "from app.database import engine; from app.models import Base; print('Models OK')"
```

---

### Task 3：FastAPI 应用完整配置

**补充：CORS 配置、全局异常处理、Pydantic schema 定义**

**schemas.py：**
```python
from pydantic import BaseModel, Field

class TaskCreate(BaseModel):
    platform: str = Field(pattern=r"^(tencent_meeting|xiaoe|bilibili|xiaohongshu|toutiao|douyin)$")
    item_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)
    content_type: str = "video"

class ErrorResponse(BaseModel):
    code: str
    message: str
```

**验证：** `curl http://localhost:8000/docs` 返回 Swagger 页面

---

### Task 4：平台/账号 CRUD API

**端点：**
```
GET    /api/platforms
POST   /api/platforms
PATCH  /api/platforms/{id}
DELETE /api/platforms/{id}
```

---

### Task 5：任务 API

**端点：**
```
GET    /api/tasks（支持 ?status=pending&page=1&page_size=20）
POST   /api/tasks
GET    /api/tasks/{id}
DELETE /api/tasks/{id}
POST   /api/tasks/{id}/retry
```

---

### Task 6：API Key 管理 API

**端点：**
```
GET    /api/keys
POST   /api/keys
DELETE /api/keys/{id}
POST   /api/keys/test  ← 测试 Key 是否有效
```

Key 值在 API 返回时只显示后 4 位：`sk-xxxx...xxxx`

---

### Task 7：WebSocket 端点

**端点：** `/ws/progress`

**消息格式：**
```json
// 服务端 → 客户端
{"type": "task_update", "task_id": 1, "step": "downloading", "step_index": 1, "step_total": 3, "step_progress": 65, "total_progress": 22, "message": "下载中 (65%)"}
{"type": "task_done", "task_id": 1}
{"type": "task_error", "task_id": 1, "step": "asr", "error": "API 超时"}
{"type": "log", "level": "info", "message": "BrowserManager: 启动 Chromium"}
```

---

### Task 8：Playwright BrowserManager

**拆分为 3 个子任务：**

**Task 8a — BrowserManager 基础封装**
```python
class BrowserManager:
    async def launch(self, platform: str, headless: bool = True) -> Browser
    async def close(self, platform: str)
    async def close_all(self)
    def health_check(self, platform: str) -> bool  # 检测是否存活
```

**Task 8b — Cookie 持久化（基于 Chrome Profile）**
```python
# 不使用 pickle 文件
# 每个平台独立 profile 目录
data/browser_profiles/
  tencent_meeting/
  xiaoe/
  bilibili/
  ...
```

**Task 8c — 多账号 Profile 隔离**
```python
# 同一平台切换账号时复用 profile
# 不同账号使用不同的 Cookie 存储文件
```

**验证：**
```python
bm = BrowserManager()
b = await bm.launch("test")
page = await b.new_page()
await page.goto("https://example.com")
assert await page.title() == "Example Domain"
await bm.close_all()
```

---

### Task 9：Vue 3 初始化

```bash
cd frontend
npm create vite@latest . -- --template vue-ts
npm install vue-router@4 pinia naive-ui axios
```

---

### Task 10：Vue API + WebSocket 封装

```
frontend/src/
  api/
    client.ts         ← axios 实例 + 拦截器
    tasks.ts          ← 任务 API
    platforms.ts      ← 平台 API
    keys.ts           ← Key API
    ws.ts             ← WebSocket 自动重连（指数退避）
```

**WebSocket 重连策略：**
```
断线 → 1s → 2s → 4s → 8s → 15s → 30s（稳定间隔）
重连成功后 → 拉取一次全量状态
清理函数：组件卸载时断开连接
```

---

### Task 11：Dashboard 页面（拆为 2 个）

**Task 11a — PlatformCard 组件：**
```vue
<template>
  <div class="platform-card" :style="{ borderLeftColor: platform.color }">
    <div class="card-header">
      <span class="name">{{ platform.displayName }}</span>
      <StatusBadge :type="platform.status" />
    </div>
    <div class="card-body">
      <div class="account-info">{{ platform.accountCount }} 个账号</div>
      <div class="output-dir">{{ platform.outputDir }}</div>
    </div>
    <div class="card-actions">
      <Button @click="fetchList(platform.name)">获取内容</Button>
    </div>
  </div>
</template>
```

**6 种状态色：**
| 状态 | 色值 | 含义 |
|------|------|------|
| connected | #22c55e | 已登录 |
| partial | #eab308 | 部分过期 |
| disconnected | #ef4444 | 未登录 |
| unconfigured | #6b7280 | 未配置 |
| fetching | #3b82f6 | 获取中 |
| error | #ef4444 | 错误 |

**Task 11b — Dashboard 页面：**
- 从 `/api/platforms` 获取平台列表
- 从 `/api/tasks` 获取汇总统计
- 展示所有 PlatformCard + 统计数字

---

### Task 12：设置页面（拆为 2 个）

**Task 12a — APIKeyManager：**
- Key 列表（名称/提供商/状态/掩码值）
- 新增表单
- 删除按钮
- 测试按钮

**Task 12b — AccountManager：**
- 各平台已绑账号列表
- 添加账号
- 登录操作
- 切换活跃账号
- 删除账号

---

### Task 13：任务中心页面（拆为 2 个）

**Task 13a — TaskList：**
- 表格展示（平台/标题/类型/状态/创建时间/操作）
- 状态过滤（全部/运行中/已完成/失败）
- 批量选择 + 删除 + 重试
- 按创建时间降序

**Task 13b — DownloadProgress：**
```vue
<template>
  <div class="download-progress">
    <div class="current-task">{{ task.title }}</div>
    <div class="sub-steps">
      <SubStep v-for="step in task.steps" :key="step.name" :step="step" />
    </div>
    <Transition name="complete-flash">
      <div v-if="task.justCompleted" class="overlay">
        <svg class="checkmark">...</svg>
        <span>下载完成</span>
      </div>
    </Transition>
  </div>
</template>
```

---

### Task 14：.gitignore + Makefile + README

**.gitignore：**
```gitignore
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
data/
*.db
*.pkl
.env
.env.local
browser_profiles/
node_modules/
.vite/
```

**Makefile：**
```makefile
install:
	cd backend && pip install -r requirements.txt
	cd frontend && npm install
	playwright install chromium

dev:
	cd backend && uvicorn app.main:app --reload --port 8000 &
	cd frontend && npm run dev

lint:
	cd backend && ruff check .
	cd frontend && npm run lint

test:
	cd backend && pytest -v
	cd frontend && npm run test:unit
```

---

### Phase 1 检查点

```
Task 1-3 完成 → 检查点 1：FastAPI 启动 + 数据库迁移 OK
Task 4-7 完成 → 检查点 2：CRUD API 全部可用 /docs 正常
Task 8a  完成 → 检查点 3：Playwright Chromium 可启动
Task 9-10完成 → 检查点 4：Vue dev server 启动 + API 调用正常
Task 11-13完成 → 检查点 5：三个页面可访问、数据正常
Task 14  完成 → Phase 1 结束

在每个检查点确认后再进入下一组任务
```

---

## 第三章：错误处理方案（三层兜底）

### 第一层 — 操作级别（秒级恢复）

```
每个操作最大重试 3 次：
  第 1 次失败 → 立即重试
  第 2 次失败 → 等待 5 秒
  第 3 次失败 → 等待 15 秒
  3 次全失败 → 进入任务级别处理
```

### 第二层 — 任务级别（分钟级恢复）

```
视频下载失败：video_status = failed，不影响转码和 ASR
转码失败：   保留原始 TS 文件，标记转码失败
ASR 失败：   transcript_status = failed
            任务整体 status = partial（不是 fail）
            任务结束时对 failed 子步骤做一次整体重试
```

### 第三层 — 系统级别（小时级恢复）

```
子步骤 5 分钟无进度更新 → 自动 kill → 重启该步骤
浏览器 10 分钟无响应 → 关闭 → 重新启动
下载连接 30 秒无数据 → 断开 → 重连 → 断点续传
ASR API 60 秒无响应 → 取消 → 重新提交

超过三级恢复仍失败 → 标记 fatal
不再自动重试
UI 显示「重试」和「跳过」按钮
```

---

## 第四章：质量门禁

### 提交前检查清单

```markdown
- [ ] ruff check 通过（0 errors）
- [ ] pytest 通过（0 failures）
- [ ] 新增 API 端点有 Pydantic schema
- [ ] 数据库迁移用 Alembic 自动生成
- [ ] .gitignore 确认 data/ 和 .env 不被跟踪
- [ ] 日志中无 API Key / Cookie 明文
```

### 不做的事

| 不做 | 理由 |
|------|------|
| API Key 加密存储 | 密钥没地方放，本地工具明文 + 脱敏足够 |
| 前端全量 TypeScript | 个人工具，类型定义只在 types/ 和 API 层 |
| 前端单元测试 | 资源利用率低，不做 |
| CI/CD 流水线 | 个人项目，不需要 |
| Web 页面内播放视频 | 本地播放器已经够用 |

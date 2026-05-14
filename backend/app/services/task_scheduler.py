"""任务调度器 — 管理下载队列和执行"""
import asyncio
import logging
from datetime import datetime
from sqlalchemy import select
from app.database import async_session
from app.models import Task, TaskStatus
from app.api.ws import manager

logger = logging.getLogger(__name__)


class TaskScheduler:
    """全局任务调度器

    策略：
    - 同一平台串行
    - 不同平台最多 2 个并发
    """

    def __init__(self, max_concurrent: int = 2):
        self._running: dict[int, asyncio.Task] = {}  # task_id -> task
        self._platform_locks: dict[str, bool] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_flag = False

    async def start(self):
        """启动调度器循环"""
        self._running_flag = True
        while self._running_flag:
            await self._process_queue()
            await asyncio.sleep(2)

    async def stop(self):
        self._running_flag = False
        for t in self._running.values():
            t.cancel()

    async def _process_queue(self):
        """从队列取待处理任务"""
        async with async_session() as db:
            result = await db.execute(
                select(Task)
                .where(Task.status == TaskStatus.PENDING)
                .order_by(Task.created_at)
                .limit(5)
            )
            pending = result.scalars().all()

        for task in pending:
            if task.id in self._running:
                continue
            # 检查同一平台是否已有运行中的任务
            platform_busy = any(
                t.platform == task.platform
                for tid, t in [(tid, None) for tid in self._running]
            )
            if platform_busy:
                continue

            self._running[task.id] = asyncio.create_task(
                self._execute_task(task)
            )
            await asyncio.sleep(0.1)

    async def _execute_task(self, task: Task):
        """执行单个任务（由子类或处理器实现具体逻辑）"""
        async with self._semaphore:
            try:
                async with async_session() as db:
                    db_task = await db.get(Task, task.id)
                    db_task.status = TaskStatus.RUNNING
                    await db.commit()

                await manager.push_task_update(
                    task_id=task.id, step="pending", step_index=0,
                    step_total=3, step_progress=0, total_progress=0,
                    message="任务开始处理",
                )

                # 实际下载逻辑由平台插件实现（Phase 2+）
                # 此处模拟执行
                for i in range(3):
                    await asyncio.sleep(1)
                    await manager.push_task_update(
                        task_id=task.id, step=["downloading", "processing", "done"][i],
                        step_index=i + 1, step_total=3,
                        step_progress=100, total_progress=int((i + 1) / 3 * 100),
                        message=f"步骤 {i + 1}/3 完成",
                    )

                async with async_session() as db:
                    db_task = await db.get(Task, task.id)
                    db_task.status = TaskStatus.DONE
                    db_task.downloaded_at = datetime.utcnow()
                    await db.commit()

                await manager.push_task_done(task.id)

            except Exception as e:
                logger.error(f"任务 {task.id} 执行失败: {e}")
                async with async_session() as db:
                    db_task = await db.get(Task, task.id)
                    db_task.status = TaskStatus.FAILED
                    db_task.error_message = str(e)[:200]
                    await db.commit()
                await manager.push_task_error(task.id, "execute", str(e)[:100])

            finally:
                self._running.pop(task.id, None)

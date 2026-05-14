"""任务调度器 — 管理下载队列和执行"""
import asyncio
import logging
from datetime import datetime, timedelta
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
    - 启动时自动恢复卡死任务
    - 3 层错误恢复由 download_handler 实现
    """

    def __init__(self, max_concurrent: int = 2):
        self._running: dict[int, asyncio.Task] = {}
        self._platform_running: dict[int, str] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running_flag = False

    async def start(self):
        """启动调度器循环"""
        self._running_flag = True
        await self._recover_dead_tasks()
        while self._running_flag:
            try:
                await self._process_queue()
            except Exception as e:
                logger.error(f"调度循环异常: {e}")
            await asyncio.sleep(2)

    async def stop(self):
        self._running_flag = False
        for t in self._running.values():
            t.cancel()

    async def _recover_dead_tasks(self):
        """恢复卡在 RUNNING 状态的任务（进程崩溃后）"""
        cutoff = datetime.utcnow() - timedelta(minutes=30)
        async with async_session() as db:
            result = await db.execute(
                select(Task).where(
                    Task.status == TaskStatus.RUNNING,
                    Task.updated_at < cutoff,
                )
            )
            dead = result.scalars().all()
            for t in dead:
                t.status = TaskStatus.PENDING
                t.error_message = "检测到异常中断，已重置为待重试"
            await db.commit()
            if dead:
                logger.info(f"恢复了 {len(dead)} 个卡死任务")

    async def _process_queue(self):
        """从队列取待处理任务"""
        async with async_session() as db:
            result = await db.execute(
                select(Task)
                .where(Task.status.in_([TaskStatus.PENDING, TaskStatus.NEW]))
                .order_by(Task.created_at)
                .limit(5)
            )
            pending = result.scalars().all()

        if not pending:
            return

        for task in pending:
            if task.id in self._running:
                continue

            # 检查同一平台是否已有运行中的任务
            platform_busy = any(
                p == task.platform
                for tid, p in self._platform_running.items()
                if tid in self._running
            )
            if platform_busy:
                continue

            self._running[task.id] = asyncio.create_task(
                self._execute_task(task)
            )
            self._platform_running[task.id] = task.platform

    async def _execute_task(self, task: Task):
        """执行单个任务（委托给 download_handler）"""
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

                from app.services.download_handler import execute_download
                await execute_download(task)

            except asyncio.CancelledError:
                async with async_session() as db:
                    db_task = await db.get(Task, task.id)
                    db_task.status = TaskStatus.CANCELLED
                    await db.commit()
                await manager.push_task_update(
                    task_id=task.id, step="cancelled",
                    step_index=0, step_total=0,
                    step_progress=0, total_progress=0,
                    message="任务已取消",
                )

            except Exception as e:
                logger.error(f"任务 {task.id} 执行失败: {e}")
                async with async_session() as db:
                    db_task = await db.get(Task, task.id)
                    # 如果 download_handler 已设置状态，不再覆盖
                    if db_task.status not in (TaskStatus.FAILED, TaskStatus.PARTIAL, TaskStatus.DONE):
                        db_task.status = TaskStatus.FAILED
                        db_task.error_message = str(e)[:200]
                    await db.commit()
                await manager.push_task_error(task.id, "execute", str(e)[:100])

            finally:
                self._running.pop(task.id, None)
                self._platform_running.pop(task.id, None)

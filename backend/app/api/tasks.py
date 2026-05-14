"""任务 CRUD API"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.models import Task, TaskStatus
from app.schemas import TaskCreate, TaskResponse, Pagination, PaginatedResponse

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
async def list_tasks(
    platform: str = None,
    status: str = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    query = select(Task).order_by(Task.created_at.desc())

    if platform:
        query = query.where(Task.platform == platform)
    if status:
        query = query.where(Task.status == status)

    # 总条数
    count_query = select(func.count()).select_from(Task)
    if platform:
        count_query = count_query.where(Task.platform == platform)
    if status:
        count_query = count_query.where(Task.status == status)
    total = (await db.execute(count_query)).scalar()

    # 分页
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    result = await db.execute(query)

    return {
        "data": [TaskResponse.model_validate(t) for t in result.scalars()],
        "pagination": Pagination(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=(total + page_size - 1) // page_size,
        ),
    }


@router.post("", status_code=201)
async def create_task(data: TaskCreate, db: AsyncSession = Depends(get_db)):
    task = Task(**data.model_dump())
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.get("/{task_id}")
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")
    await db.delete(task)
    await db.commit()


@router.post("/{task_id}/retry")
async def retry_task(task_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "任务不存在")
    task.status = TaskStatus.PENDING
    task.retry_count = 0
    task.error_message = None
    await db.commit()
    return {"message": "任务已重置为待重试"}

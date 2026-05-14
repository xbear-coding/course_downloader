"""平台与账号 CRUD API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models import Platform, Account
from app.schemas import PlatformCreate, PlatformResponse, AccountCreate, AccountResponse

router = APIRouter(prefix="/api/platforms", tags=["platforms"])


@router.get("", response_model=list[PlatformResponse])
async def list_platforms(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Platform).order_by(Platform.sort_order))
    return result.scalars().all()


@router.post("", response_model=PlatformResponse, status_code=201)
async def create_platform(data: PlatformCreate, db: AsyncSession = Depends(get_db)):
    platform = Platform(**data.model_dump())
    db.add(platform)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "平台名称已存在")
    await db.refresh(platform)
    return platform


@router.get("/{platform_id}", response_model=PlatformResponse)
async def get_platform(platform_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Platform).where(Platform.id == platform_id))
    platform = result.scalar_one_or_none()
    if not platform:
        raise HTTPException(404, "平台不存在")
    return platform


@router.delete("/{platform_id}", status_code=204)
async def delete_platform(platform_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Platform).where(Platform.id == platform_id))
    platform = result.scalar_one_or_none()
    if not platform:
        raise HTTPException(404, "平台不存在")
    await db.delete(platform)
    await db.commit()


ALLOWED_PLATFORM_UPDATES = {"enabled", "output_dir", "display_name", "sort_order"}

@router.patch("/{platform_id}", response_model=PlatformResponse)
async def update_platform(
    platform_id: int, data: dict, db: AsyncSession = Depends(get_db)
):
    """更新平台设置（仅允许白名单字段）"""
    result = await db.execute(select(Platform).where(Platform.id == platform_id))
    platform = result.scalar_one_or_none()
    if not platform:
        raise HTTPException(404, "平台不存在")
    for key, value in data.items():
        if key in ALLOWED_PLATFORM_UPDATES:
            setattr(platform, key, value)
    await db.commit()
    await db.refresh(platform)
    return platform


# ── 账号 ──

@router.get("/{platform_id}/accounts", response_model=list[AccountResponse])
async def list_accounts(platform_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Account).where(Account.platform_id == platform_id)
    )
    return result.scalars().all()


@router.post("/{platform_id}/accounts", response_model=AccountResponse, status_code=201)
async def create_account(
    platform_id: int, data: AccountCreate, db: AsyncSession = Depends(get_db)
):
    account = Account(platform_id=platform_id, name=data.name)
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account

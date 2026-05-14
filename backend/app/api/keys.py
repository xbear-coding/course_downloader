"""API Key 管理"""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import APIKey
from app.schemas import APIKeyCreate, APIKeyResponse

router = APIRouter(prefix="/api/keys", tags=["api-keys"])


def mask_key(key: str) -> str:
    """脱敏显示：sk-qvjf...hsrh"""
    if len(key) <= 12:
        return "***"
    return key[:4] + "..." + key[-4:]


@router.get("", response_model=list[APIKeyResponse])
async def list_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(APIKey))
    keys = result.scalars().all()
    # 脱敏
    for k in keys:
        k.key_value = mask_key(k.key_value)
    return keys


@router.post("", response_model=APIKeyResponse, status_code=201)
async def create_key(data: APIKeyCreate, db: AsyncSession = Depends(get_db)):
    key = APIKey(**data.model_dump())
    db.add(key)
    await db.commit()
    await db.refresh(key)
    key.key_value = mask_key(key.key_value)
    return key


@router.delete("/{key_id}", status_code=204)
async def delete_key(key_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(404, "Key 不存在")
    await db.delete(key)
    await db.commit()


@router.post("/{key_id}/test")
async def test_key(key_id: int, db: AsyncSession = Depends(get_db)):
    """测试 API Key 是否有效"""
    result = await db.execute(select(APIKey).where(APIKey.id == key_id))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(404, "Key 不存在")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.siliconflow.cn/v1/models",
                headers={"Authorization": f"Bearer {key.key_value}"},
            )
            if resp.status_code == 200:
                return {"success": True, "message": "Key 有效"}
            else:
                return {"success": False, "message": f"API 返回 {resp.status_code}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)[:50]}"}

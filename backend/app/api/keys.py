"""API Key 管理（加密存储）"""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import get_db
from app.models import APIKey
from app.schemas import APIKeyCreate, APIKeyResponse
from app.services.crypto import encrypt, decrypt

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
    responses = [APIKeyResponse.model_validate(k) for k in keys]
    for r in responses:
        try:
            plain = decrypt(r.key_value)
            r.key_value = mask_key(plain)
        except Exception:
            r.key_value = "***"
    return responses


@router.post("", response_model=APIKeyResponse, status_code=201)
async def create_key(data: APIKeyCreate, db: AsyncSession = Depends(get_db)):
    encrypted_value = encrypt(data.key_value)
    key = APIKey(
        name=data.name,
        key_value=encrypted_value,
        provider=data.provider,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    response = APIKeyResponse.model_validate(key)
    response.key_value = mask_key(data.key_value)  # 用原文脱敏展示
    return response


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
        plain = decrypt(key.key_value)
    except Exception:
        return {"success": False, "message": "解密失败，加密密钥可能已变更"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.siliconflow.cn/v1/models",
                headers={"Authorization": f"Bearer {plain}"},
            )
            if resp.status_code == 200:
                return {"success": True, "message": "Key 有效"}
            return {"success": False, "message": f"API 返回 {resp.status_code}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)[:50]}"}

"""测试 API Key 加解密"""
import os
import pytest
from cryptography.fernet import Fernet
import app.config as config


@pytest.fixture(autouse=True)
def setup_env():
    """每个测试前设置固定的加密密钥并清空缓存"""
    import app.services.crypto as crypto_mod
    _saved = crypto_mod._key_cache
    crypto_mod._key_cache = None

    key = Fernet.generate_key().decode()
    os.environ["COURSE_DOWNLOADER_KEY"] = key
    yield
    os.environ.pop("COURSE_DOWNLOADER_KEY", None)
    crypto_mod._key_cache = _saved


class TestEncryptDecrypt:
    """加密/解密往返测试"""

    def test_roundtrip(self):
        from app.services.crypto import encrypt, decrypt
        plain = "sk-abcdefghijklmnopqrstuvwxyz123456"
        cipher = encrypt(plain)
        assert cipher != plain
        assert decrypt(cipher) == plain

    def test_different_cipher_each_time(self):
        """同一明文每次加密结果不同（Fernet 使用随机 IV）"""
        from app.services.crypto import encrypt
        plain = "sk-test-key-value"
        c1 = encrypt(plain)
        c2 = encrypt(plain)
        assert c1 != c2

    def test_empty_string(self):
        from app.services.crypto import encrypt, decrypt
        assert decrypt(encrypt("")) == ""

    def test_special_characters(self):
        from app.services.crypto import encrypt, decrypt
        plain = "sk-!@#$%^&*()_+-=[]{}|;':\",./<>?`~"
        assert decrypt(encrypt(plain)) == plain

    def test_long_key(self):
        from app.services.crypto import encrypt, decrypt
        plain = "sk-" + "x" * 500
        assert decrypt(encrypt(plain)) == plain


class TestMaskKey:
    """脱敏函数"""

    def test_mask_long_key(self):
        from app.api.keys import mask_key
        result = mask_key("sk-abcdefghijklmnopqrstuvwxyz")
        assert result == "sk-a...wxyz"
        assert "abcdefgh" not in result

    def test_mask_short_key(self):
        from app.api.keys import mask_key
        assert mask_key("short") == "***"

    def test_mask_boundary(self):
        from app.api.keys import mask_key
        # Exactly 12 chars
        assert mask_key("123456789012") == "***"
        # 13 chars
        assert mask_key("1234567890123") == "1234...0123"


class TestAPIKeyStorage:
    """验证 API Key 在 DB 中为密文存储"""

    async def test_list_returns_masked(self, client):
        await client.post("/api/keys", json={
            "name": "Visible",
            "key_value": "sk-visible-key-value-abcdefgh",
        })
        resp = await client.get("/api/keys")
        data = resp.json()
        assert len(data) == 1
        # key_value 应该脱敏，不包含完整 key
        assert "visible" not in data[0]["key_value"]
        assert data[0]["key_value"] != "sk-visible-key-value-abcdefgh"

    async def test_stored_encrypted(self, client, db_session):
        """通过注入的 db_session 验证 DB 中为密文"""
        await client.post("/api/keys", json={
            "name": "SecretKey",
            "key_value": "sk-my-secret-key-value-12345",
            "provider": "siliconflow",
        })
        from app.models import APIKey
        from sqlalchemy import select
        result = await db_session.execute(select(APIKey))
        key = result.scalar_one()
        assert key.key_value != "sk-my-secret-key-value-12345"
        assert not key.key_value.startswith("sk-")
        # Fernet 密文是 base64 编码，不含明文 key 的特征
        assert len(key.key_value) > 50


class TestEncryptionKeyMissing:
    """加密密钥缺失时的行为"""

    def test_auto_generates_key(self, tmp_path, monkeypatch):
        """当环境变量不存在时，自动生成密钥并保存到 .env"""
        import app.services.crypto as crypto_mod
        # 清空缓存
        crypto_mod._key_cache = None
        monkeypatch.delenv("COURSE_DOWNLOADER_KEY", raising=False)
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)

        result = crypto_mod.encrypt("test")
        assert result != "test"

        # 验证 .env 文件已创建
        env_file = tmp_path / ".env"
        assert env_file.exists()
        content = env_file.read_text()
        assert "COURSE_DOWNLOADER_KEY" in content

"""API Key 加解密 — AES (Fernet)

策略：
1. 优先使用环境变量 COURSE_DOWNLOADER_KEY
2. 其次读取 .env 文件中保存的密钥
3. 都不存在时自动生成并保存到 .env
4. 密钥在进程内缓存，避免重复读写 .env
"""
import os
import re
import logging
from cryptography.fernet import Fernet
import app.config as config

logger = logging.getLogger(__name__)

ENV_KEY_NAME = "COURSE_DOWNLOADER_KEY"


def _env_path():
    return config.BASE_DIR / ".env"

# 进程内缓存
_key_cache: bytes | None = None


def _load_key() -> bytes | None:
    """从环境变量或 .env 文件读取密钥"""
    key_str = os.getenv(ENV_KEY_NAME)
    if key_str:
        return key_str.encode()

    if _env_path().exists():
        content = _env_path().read_text(encoding="utf-8")
        m = re.search(rf'{ENV_KEY_NAME}="?([^"\n]+)"?', content)
        if m:
            return m.group(1).encode()
    return None


def _save_key(key_str: str):
    """将密钥写入 .env 文件"""
    line = f'{ENV_KEY_NAME}="{key_str}"\n'
    if _env_path().exists():
        content = _env_path().read_text(encoding="utf-8")
        if ENV_KEY_NAME in content:
            content = re.sub(rf'{ENV_KEY_NAME}=.*\n', line, content)
        else:
            content += "\n" + line
        _env_path().write_text(content, encoding="utf-8")
    else:
        _env_path().write_text(line, encoding="utf-8")


def _get_or_create_key() -> bytes:
    """获取加密密钥（带缓存）"""
    global _key_cache
    if _key_cache:
        return _key_cache

    key = _load_key()
    if key:
        _key_cache = key
        return key

    # 自动生成
    new_key = Fernet.generate_key()
    key_str = new_key.decode()
    _save_key(key_str)
    # 同时也设到环境变量，保证同进程后续调用一致
    os.environ[ENV_KEY_NAME] = key_str
    _key_cache = new_key
    logger.warning(f"已自动生成加密密钥，保存在 {_env_path()}，请勿丢失！")
    return new_key


def encrypt(plaintext: str) -> str:
    """加密明文 → 密文字符串"""
    key = _get_or_create_key()
    return Fernet(key).encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """解密密文 → 明文字符串"""
    key = _get_or_create_key()
    return Fernet(key).decrypt(ciphertext.encode()).decode()

"""Alembic 数据库迁移配置"""
from logging.config import fileConfig
from sqlalchemy import pool, create_engine
from alembic import context
import sys
from pathlib import Path

# 添加应用路径
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

from models import Base  # noqa: E402
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url").replace("+aiosqlite", "")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url").replace("+aiosqlite", "")
    connectable = create_engine(url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

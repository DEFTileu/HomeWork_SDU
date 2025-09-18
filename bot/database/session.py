from __future__ import annotations

import asyncio
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase

from bot.config import settings
from urllib.parse import urlsplit, urlunsplit


class Base(DeclarativeBase):
    pass


engine: AsyncEngine | None = None
async_session_maker: async_sessionmaker[AsyncSession] | None = None


def _normalize_database_url(url: str) -> str:
    # Ensure async driver for MySQL
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme.startswith("mysql") and "+" not in scheme:
        # convert mysql:// to mysql+asyncmy://
        scheme = "mysql+asyncmy"
    elif scheme.startswith("mysql+") and "async" not in scheme:
        # e.g., mysql+pymysql -> mysql+asyncmy
        scheme = "mysql+asyncmy"
    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def _require_database_url() -> str:
    if not settings.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Example: mysql+asyncmy://user:pass@localhost:3306/sdu_hw"
        )
    return _normalize_database_url(settings.DATABASE_URL)


def init_engine() -> None:
    global engine, async_session_maker
    if engine is None:
        engine = create_async_engine(_require_database_url(), echo=False, pool_pre_ping=True)
        async_session_maker = async_sessionmaker(engine, expire_on_commit=False)


async def init_models() -> None:
    from .models import User  # noqa: F401 - ensure models are imported for metadata

    init_engine()
    assert engine is not None
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # lightweight compatibility migration(s)
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS password VARCHAR(255)"))
        except Exception:
            # MySQL < 8 may not support IF NOT EXISTS; try probing column existence
            try:
                await conn.execute(text("SELECT `password` FROM users LIMIT 0"))
            except Exception:
                # finally, add column without IF NOT EXISTS
                await conn.execute(text("ALTER TABLE users ADD COLUMN password VARCHAR(255)"))
        # ensure legacy password_hash is nullable to avoid NOT NULL constraint errors
        try:
            await conn.execute(text("ALTER TABLE users MODIFY password_hash VARCHAR(255) NULL"))
        except Exception:
            pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    init_engine()
    assert async_session_maker is not None
    async with async_session_maker() as session:
        yield session



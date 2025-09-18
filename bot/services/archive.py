from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import Homework, HomeworkArchive


async def move_done_homeworks_to_archive(db: AsyncSession) -> int:
    """Архивируем выполненные домашние задания, но не удаляем их"""
    # Обновляем выполненные задания, помечая их как архивные
    result = await db.execute(
        update(Homework)
        .where(Homework.is_done.is_(True), Homework.is_archived.is_(False))
        .values(is_archived=True, archived_at=datetime.utcnow())
    )
    count = result.rowcount
    await db.commit()
    return count


async def get_archive_by_week(db: AsyncSession, user_id: int, weeks_ago: int = 0) -> list[Homework]:
    """Получаем архивные домашние задания за определенную неделю"""
    # week range [monday 00:00, next monday 00:00)
    now = datetime.utcnow()
    start_of_week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start = start_of_week - timedelta(weeks=weeks_ago)
    end = start + timedelta(weeks=1)

    res = await db.execute(
        select(Homework)
        .where(
            Homework.user_id == user_id,
            Homework.is_archived.is_(True),
            Homework.archived_at >= start,
            Homework.archived_at < end,
        )
        .order_by(Homework.archived_at.desc())
    )
    return list(res.scalars().all())

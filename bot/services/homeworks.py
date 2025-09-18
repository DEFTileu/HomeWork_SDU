from __future__ import annotations

from datetime import datetime
from typing import Iterable, Literal, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bot.database.models import Homework, HomeworkMedia

MediaType = Literal["photo", "video", "document"]


async def add_homework(
    db: AsyncSession,
    user_id: int,
    subject: str,
    description: str,
    deadline: datetime | None,
    media_list: Sequence[tuple[MediaType, str]] | None = None,
    lesson_id: int | None = None,  # Добавляем связь с уроком
) -> Homework:
    hw = Homework(
        user_id=user_id,
        subject=subject,
        description=description,
        deadline=deadline,
        lesson_id=lesson_id  # Связываем с уроком
    )
    db.add(hw)
    await db.flush()

    if media_list:
        for file_type, file_id in media_list:
            db.add(HomeworkMedia(homework_id=hw.id, file_type=file_type, file_id=file_id))

    await db.commit()
    await db.refresh(hw)
    return hw


async def get_homeworks(db: AsyncSession, user_id: int, only_active: bool = True) -> list[Homework]:
    stmt = (
        select(Homework)
        .options(joinedload(Homework.media), joinedload(Homework.lesson))  # Загружаем связанный урок
        .where(Homework.user_id == user_id, Homework.is_archived.is_(False))  # Исключаем архивные
        .order_by(Homework.is_done.asc(), Homework.deadline.is_(None), Homework.deadline.asc())
    )
    if only_active:
        stmt = stmt.where(Homework.is_done.is_(False))
    res = await db.execute(stmt)
    return list(res.scalars().unique())


async def update_homework_status(db: AsyncSession, homework_id: int, is_done: bool) -> None:
    from datetime import datetime
    values = {"is_done": is_done, "done_at": datetime.utcnow() if is_done else None}
    stmt = update(Homework).where(Homework.id == homework_id).values(**values)
    await db.execute(stmt)
    await db.commit()

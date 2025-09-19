from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bot.database.models import Homework, HomeworkMedia, ScheduleLesson

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
    from datetime import datetime, timezone
    values = {"is_done": is_done, "done_at": datetime.now(timezone.utc) if is_done else None}
    stmt = update(Homework).where(Homework.id == homework_id).values(**values)
    await db.execute(stmt)
    await db.commit()


async def calculate_deadline_from_lesson(db: AsyncSession, lesson_id: int) -> datetime | None:
    """Рассчитывает дедлайн на основе следующего урока"""
    # Получаем урок
    lesson = await db.get(ScheduleLesson, lesson_id)
    if not lesson:
        return None

    now = datetime.now()
    current_weekday = now.isoweekday()  # 1=Monday, 7=Sunday

    lesson_day = lesson.day_of_week  # 1-6 (Mon-Sat)
    lesson_start_time = lesson.start_time

    # Рассчитываем дни до следующего урока
    days_until = (lesson_day - current_weekday) % 7
    if days_until == 0:
        # Сегодня - проверяем время
        lesson_time = datetime.strptime(lesson_start_time, "%H:%M").time()
        lesson_datetime = now.replace(hour=lesson_time.hour, minute=lesson_time.minute, second=0, microsecond=0)
        if lesson_datetime <= now:
            days_until = 7  # Следующая неделя

    # Создаем дату следующего урока
    next_lesson_date = now + timedelta(days=days_until)
    lesson_time = datetime.strptime(lesson_start_time, "%H:%M").time()
    deadline = next_lesson_date.replace(
        hour=lesson_time.hour,
        minute=lesson_time.minute,
        second=0,
        microsecond=0
    )

    return deadline

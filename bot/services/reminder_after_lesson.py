from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from bot.config import settings
from bot.database.models import ScheduleLesson, User
from bot.database.session import get_session


def _now_local() -> datetime:
    return datetime.now(ZoneInfo(settings.TIMEZONE))


async def unified_lesson_check(bot: Bot) -> None:
    """Объединенная проверка: напоминания о домашках + уведомления о следующих уроках"""
    now = _now_local()
    day_idx = now.isoweekday()  # 1..7, our lessons use 1..6
    if day_idx > 6:  # Skip Sunday
        return

    current_minute = now.minute
    current_hour = now.hour

    # Работаем только в XX:15
    if current_minute != 15:
        return

    async for db in get_session():
        # Получаем всех пользователей с telegram_id
        users = (await db.execute(select(User).where(User.telegram_id.is_not(None)))).scalars().all()

        for user in users:
            # Получаем расписание пользователя на сегодня
            lessons = (
                await db.execute(
                    select(ScheduleLesson)
                    .where(
                        ScheduleLesson.user_id == user.id,
                        ScheduleLesson.day_of_week == day_idx,
                    )
                )
            ).scalars().all()

            # 1. ПРОВЕРЯЕМ ДОМАШНИЕ ЗАДАНИЯ (для уроков, заканчивающихся в XX:20)
            for lesson in lessons:
                end_time = lesson.end_time  # 'HH:MM'

                try:
                    lesson_end = datetime.strptime(end_time, "%H:%M").time()

                    # Проверяем, что урок заканчивается в XX:20 через 5 минут
                    if lesson_end.minute == 20 and lesson_end.hour == current_hour:
                        kb = InlineKeyboardMarkup(
                            inline_keyboard=[
                                [
                                    InlineKeyboardButton(text="✅ Да", callback_data=f"dz:{lesson.id}:yes"),
                                    InlineKeyboardButton(text="❌ Нет", callback_data=f"dz:{lesson.id}:no"),
                                ]
                            ]
                        )

                        title = lesson.course_code or lesson.title or "Урок"
                        lesson_info = f"{title}"
                        if lesson.lesson_type:
                            lesson_info += f" ({lesson.lesson_type})"
                        if lesson.room:
                            lesson_info += f" - {lesson.room}"

                        try:
                            await bot.send_message(
                                user.telegram_id,
                                f"🎓 Занятие '{lesson_info}' скоро закончится (через 5 минут).\n\n📝 Было ли домашнее задание?",
                                reply_markup=kb,
                            )
                        except Exception as e:
                            print(f"Ошибка отправки вопроса о домашке пользователю {user.telegram_id}: {e}")

                except ValueError:
                    continue

            # 2. НАПОМИНАНИЯ О СЛЕДУЮЩИХ УРОКАХ (через 15 минут)
            next_lesson_time = (now + timedelta(minutes=15)).time()
            next_lessons = []

            for lesson in lessons:
                try:
                    lesson_start = datetime.strptime(lesson.start_time, "%H:%M").time()

                    # Проверяем, начинается ли урок через 15 минут (±2 минуты для точности)
                    time_diff = abs((datetime.combine(now.date(), lesson_start) -
                                   datetime.combine(now.date(), next_lesson_time)).total_seconds())

                    if time_diff <= 120:  # В пределах 2 минут
                        next_lessons.append(lesson)

                except ValueError:
                    continue

            # Отправляем напоминания о следующих уроках
            for lesson in next_lessons:
                title = lesson.course_code or lesson.title or "Урок"
                lesson_info = f"{title}"
                if lesson.lesson_type:
                    lesson_info += f" ({lesson.lesson_type})"
                if lesson.room:
                    lesson_info += f" - {lesson.room}"
                if lesson.teacher:
                    lesson_info += f" - {lesson.teacher}"

                try:
                    await bot.send_message(
                        user.telegram_id,
                        f"⏰ Напоминание: через 15 минут начинается занятие\n\n"
                        f"🎓 {lesson_info}\n"
                        f"⏰ Время: {lesson.start_time}-{lesson.end_time}",
                    )
                except Exception as e:
                    print(f"Ошибка отправки напоминания пользователю {user.telegram_id}: {e}")


# Оставляем старую функцию для совместимости, но делаем её простой заглушкой
async def ask_after_lesson_job(bot: Bot) -> None:
    """Устаревшая функция - теперь всё делает unified_lesson_check"""
    pass


# Переименовываем основную функцию для ясности
async def check_homework_after_lesson_ends(bot: Bot) -> None:
    """Переименовано в unified_lesson_check для ясности"""
    await unified_lesson_check(bot)

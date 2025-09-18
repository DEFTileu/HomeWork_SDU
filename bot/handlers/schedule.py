from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from sqlalchemy import select

from bot.database.session import get_session
from bot.database.models import User, UserSession
from bot.services.schedule import import_schedule_html, fetch_and_import_schedule_new


router = Router(name="schedule")


@router.message(Command("import_schedule"))
async def import_schedule_cmd(message: Message) -> None:
    if not message.reply_to_message or not message.reply_to_message.document:
        await message.answer("Пришлите HTML расписания и ответьте командой /import_schedule на этот файл.")
        return

    file = message.reply_to_message.document
    file_obj = await message.bot.get_file(file.file_id)
    file_path = file_obj.file_path
    file_bytes = await message.bot.download_file(file_path)
    html = file_bytes.read().decode("utf-8", errors="ignore")

    async for db in get_session():
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one_or_none()
        if not user:
            await message.answer("Сначала выполните /login")
            return
        count = await import_schedule_html(db, user.id, html)
        await message.answer(f"Импортировано занятий: {count}")


def schedule_inline_keyboard(current_part: int) -> InlineKeyboardMarkup:
    # current_part: 0 = первая часть (ПН-СР), 1 = вторая часть (ЧТ-СБ)
    if current_part == 0:
        # Показываем первую часть, кнопка "Вперёд" ведет на вторую часть
        text = "▶️ Вперёд"
        next_part = 1
    else:
        # Показываем вторую часть, кнопка "Назад" ведет на первую часть
        text = "◀️ Назад"
        next_part = 0

    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=f"schedule_part_{next_part}")]]
    )


async def get_formatted_schedule(user_id: int, part: int = 0) -> str:
    from sqlalchemy import select
    from collections import defaultdict
    from tabulate import tabulate
    from bot.database.models import ScheduleLesson

    # days split
    days = ["MO", "TU", "WE"] if part == 0 else ["TH", "FR", "SA"]
    day_map = {1: "MO", 2: "TU", 3: "WE", 4: "TH", 5: "FR", 6: "SA"}

    lessons = []
    async for db in get_session():
        lessons = (
            await db.execute(
                select(ScheduleLesson)
                .where(ScheduleLesson.user_id == user_id)
            )
        ).scalars().all()

    # Создаем таблицу расписания
    schedule_table = defaultdict(lambda: {day: "" for day in days})

    # Собираем уникальные временные слоты
    time_slots = set()

    for lesson in lessons:
        day_abbreviation = day_map.get(lesson.day_of_week, "")
        if day_abbreviation in days:
            time_key = f"{lesson.start_time}-{lesson.end_time}"
            time_slots.add((lesson.start_time, lesson.end_time))

            # Фор��ируем содержимое ячейки: код курса и кабинет
            course_code = lesson.course_code or ""
            room = lesson.room or ""

            # Создаем содержимое ячейки для таблицы
            cell_content = f"{course_code}\n{room}" if course_code and room else (course_code or room or "")
            schedule_table[time_key][day_abbreviation] = cell_content

    # Сортируем временные слоты
    time_slots = sorted(list(time_slots))

    if not time_slots:
        return "Расписание не найдено"

    # Формируем данные для таблицы
    headers = ["T/D"] + days
    table_data = []

    for start_time, end_time in time_slots:
        time_key = f"{start_time}-{end_time}"

        # Проверяем, есть ли занятия в этот временной слот
        has_lessons = any(schedule_table[time_key][day] for day in days)
        if not has_lessons:
            continue

        # Создаем строку таблицы
        time_cell = f"{start_time}\n{end_time}"
        row = [time_cell] + [schedule_table[time_key][day] for day in days]
        table_data.append(row)

    if not table_data:
        return "Расписание не найдено"

    # Создаем таблицу с помощью tabulate
    table_string = tabulate(table_data, headers, tablefmt="grid", colalign=("center", "center", "center", "center"))

    return table_string




@router.message(Command("schedule"))
async def schedule_handler(message: Message) -> None:
    from sqlalchemy import select
    from bot.database.models import ScheduleLesson

    async for db in get_session():
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one_or_none()

        # Если пользователя нет, но есть расписание, создаем временного пользователя
        if not user:
            # Проверяем, есть ли вообще расписание в системе
            any_schedule = (await db.execute(select(ScheduleLesson).limit(1))).scalar_one_or_none()
            if any_schedule:
                # Создаем временного пользователя
                temp_user = User(
                    telegram_id=message.from_user.id,
                    username=f"temp_user_{message.from_user.id}",
                    password="temp"
                )
                db.add(temp_user)
                await db.commit()
                await db.refresh(temp_user)
                user = temp_user
            else:
                await message.answer("❌ Сначала выполните /login")
                return

        text = await get_formatted_schedule(user.id, 0)
        await message.answer(f"<pre>{text}</pre>", reply_markup=schedule_inline_keyboard(0))


@router.callback_query(F.data.startswith("schedule_part_"))
async def schedule_callback_handler(callback: CallbackQuery) -> None:
    from sqlalchemy import select
    user_id = callback.from_user.id
    # Извлекаем часть расписания, на которую нужно переключиться
    part = int(callback.data.split("_")[2])

    async for db in get_session():
        user = (await db.execute(select(User).where(User.telegram_id == user_id))).scalar_one_or_none()
        if not user:
            await callback.answer("Сначала /login", show_alert=True)
            return

        # Получаем расписание для нужной части
        text = await get_formatted_schedule(user.id, part)

        try:
            # Обновляем сообщение с новой частью расписания и соответствующей кнопкой
            await callback.message.edit_text(f"<pre>{text}</pre>", reply_markup=schedule_inline_keyboard(part))
        except Exception:
            pass
        await callback.answer()



@router.message(Command("parse"))
async def parse_schedule_cmd(message: Message) -> None:
    """Команда для автомат��ического обновления расписания с сайта SDU"""
    async for db in get_session():
        # Проверяем, что пользователь авторизован
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one_or_none()
        if not user:
            await message.answer("❌ Сначала выполните /login для авторизации")
            return

        # Проверяем, что у пользователя есть правильные учетные данные (не временные)
        if not user.username or not user.password or user.username.startswith('temp_user_') or user.password == 'temp':
            await message.answer(
                "❌ У вас нет действительных учетных данных SDU.\n\n"
                "Выполните /login чтобы войти в систему с вашими реальными данными SDU, "
                "после чего вы сможете обновлять расписание."
            )
            return

        # Отправляем сообщение о начале парсинга
        status_message = await message.answer("🔄 Обновляю расписание с сайта SDU...")

        try:
            # Используем новую функцию парсинга с username и password
            count = await fetch_and_import_schedule_new(
                db=db,
                user_id=user.id,
                username=user.username,
                password=user.password
            )

            if count > 0:
                await status_message.edit_text(f"✅ Расписание успешно обновлено!\nИмпортировано занятий: {count}")
            else:
                await status_message.edit_text("⚠️ Расписание обновлено, но новых занятий не найдено")

        except Exception as e:
            await status_message.edit_text(f"❌ Ошибка при обновлении расписания:\n{str(e)}")
            # Логируем ошибку
            import logging
            logging.exception("Ошибка при парсинга расписания")

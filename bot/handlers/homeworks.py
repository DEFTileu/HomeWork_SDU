from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.database.session import get_session
from bot.database.models import User, Homework
from bot.services.homeworks import get_homeworks, update_homework_status, add_homework


class HomeworkState(StatesGroup):
    collecting_homework = State()


router = Router(name="homeworks")


def _format_deadline(hw: Homework) -> str:
    """Форматирует дедлайн для отображения"""
    from datetime import datetime

    # Если есть явно указанный дедлайн
    if hw.deadline:
        return hw.deadline.strftime("%d.%m.%Y %H:%M")

    # Если домашка связана с уроком, рассчитываем до следующего урока
    if hw.lesson:
        now = datetime.now()
        current_weekday = now.isoweekday()  # 1=Monday, 7=Sunday

        lesson_day = hw.lesson.day_of_week  # 1-6 (Mon-Sat)
        lesson_start_time = hw.lesson.start_time

        # Рассчитываем дни до следующего урока
        days_until = (lesson_day - current_weekday) % 7
        if days_until == 0:
            # Сегодня - проверяем время
            lesson_time = datetime.strptime(lesson_start_time, "%H:%M").time()
            lesson_datetime = now.replace(hour=lesson_time.hour, minute=lesson_time.minute, second=0, microsecond=0)
            if lesson_datetime <= now:
                days_until = 7  # Следующая неделя

        if days_until == 0:
            return f"Сегодня к {lesson_start_time}"
        elif days_until == 1:
            return f"Завтра к {lesson_start_time}"
        else:
            return f"Через {days_until} дн. к {lesson_start_time}"

    # Если нет ни дедлайна, ни урока
    return "Не указан"


@router.message(Command("homeworks"))
async def list_homeworks(message: Message) -> None:
    async for db in get_session():
        # find user by telegram id
        from sqlalchemy import select
        from bot.database.models import ScheduleLesson

        res = await db.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = res.scalar_one_or_none()

        # Если пользователя нет, проверяем есть ли у него расписание
        if not user:
            # Пытаемся найти расписание по telegram_id через других пользователей
            # или создаем временного пользователя если есть расписание
            schedule_check = await db.execute(
                select(ScheduleLesson).limit(1)
            )
            has_any_schedule = schedule_check.scalar_one_or_none()

            if has_any_schedule:
                # Создаем временного пользователя для работы с расписанием
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
                await message.answer("Сначала выполните /login")
                return

        items = await get_homeworks(db, user_id=user.id, only_active=True)  # Только активные
        if not items:
            await message.answer("Активных домашних заданий нет.")
            return

        # Получаем расписание для расчета дедлайнов
        from bot.database.models import ScheduleLesson
        from datetime import datetime

        now = datetime.now()
        current_weekday = now.isoweekday()  # 1=Monday, 7=Sunday

        # Получаем расписание пользователя
        schedule_lessons = (await db.execute(
            select(ScheduleLesson).where(ScheduleLesson.user_id == user.id)
        )).scalars().all()

        # Формируем кнопки для активных заданий
        kb_rows = []

        for h in items:
            # Рассчитываем дедлайн до следующего урока
            deadline_text = "—"
            if h.lesson:
                # Находим следующее занятие этого типа
                lesson_day = h.lesson.day_of_week  # 1-6 (Mon-Sat)
                lesson_start_time = h.lesson.start_time

                # Рассчитываем дни до следующего урока
                days_until = (lesson_day - current_weekday) % 7
                if days_until == 0:
                    # Сегодня - проверяем время
                    lesson_time = datetime.strptime(lesson_start_time, "%H:%M").time()
                    lesson_datetime = now.replace(hour=lesson_time.hour, minute=lesson_time.minute, second=0, microsecond=0)
                    if lesson_datetime <= now:
                        days_until = 7  # Следующая неделя

                if days_until == 0:
                    deadline_text = "Сегодня"
                elif days_until == 1:
                    deadline_text = "Завтра"
                else:
                    deadline_text = f"Через {days_until} дн."

            # Создаем красивое название с информацией об уроке и дедлайне
            lesson_info = ""
            if h.lesson:
                lesson_info = f"{h.lesson.course_code or h.lesson.title or 'Урок'} • "

            button_text = f"📝 {lesson_info}{h.subject}"
            if deadline_text != "—":
                button_text += f" ({deadline_text})"

            kb_rows.append([InlineKeyboardButton(text=button_text, callback_data=f"hw:{h.id}")])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

        # Показываем только активные задания
        active_count = len(items)
        stats_text = f"📝 Активных заданий: {active_count}"

        await message.answer(f"Ваши домашние задания:\n\n{stats_text}", reply_markup=kb)


@router.callback_query(F.data.startswith("hw:"))
async def hw_detail(cb: CallbackQuery) -> None:
    hw_id = int(cb.data.split(":", 1)[1])
    async for db in get_session():
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        # Явно загружаем медиафайлы с homework и используем unique() для устранения дубликатов
        res = await db.execute(
            select(Homework)
            .options(joinedload(Homework.media))
            .where(Homework.id == hw_id)
        )
        hw = res.unique().scalar_one_or_none()
        if not hw:
            await cb.answer("Не найдено", show_alert=True)
            return

        text = (
            f"<b>{hw.subject}</b>\n"
            f"{hw.description}\n\n"
            f"Дедлайн: {_format_deadline(hw)}\n"
            f"Статус: {'✅ Выполнено' if hw.is_done else '⏳ В процессе'}"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сделано" if not hw.is_done else "↩️ Вернуть в работу", callback_data=f"hwdone:{hw.id}:{0 if not hw.is_done else 1}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="hwback")],
        ])

        # Проверяем тип текущего сообщения
        current_is_photo = bool(cb.message.photo)
        current_is_video = bool(cb.message.video)
        current_is_document = bool(cb.message.document)
        current_is_text = not (current_is_photo or current_is_video or current_is_document)

        # Если у домашки есть медиафайлы
        if hw.media:
            media_file = hw.media[0]  # Берем первый медиафайл

            # Если текущее сообщение уже содержит медиа того же типа - редактируем caption
            if ((current_is_photo and media_file.file_type == "photo") or
                (current_is_video and media_file.file_type == "video") or
                (current_is_document and media_file.file_type == "document")):
                try:
                    await cb.message.edit_caption(caption=text, reply_markup=kb, parse_mode="HTML")
                    await cb.answer()
                    return
                except Exception:
                    pass

            # Если текущее сообщение текстовое или другого типа медиа - удаляем и отправляем новое
            try:
                await cb.message.delete()
            except Exception:
                pass

            # Отправляем медиа-сообщение
            try:
                if media_file.file_type == "photo":
                    await cb.message.answer_photo(media_file.file_id, caption=text, reply_markup=kb, parse_mode="HTML")
                elif media_file.file_type == "video":
                    await cb.message.answer_video(media_file.file_id, caption=text, reply_markup=kb, parse_mode="HTML")
                elif media_file.file_type == "document":
                    await cb.message.answer_document(media_file.file_id, caption=text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                # Если медиафайл недоступен, отправляем текстовое сообщение
                await cb.message.answer(f"{text}\n\n⚠️ Медиафайл недоступен", reply_markup=kb, parse_mode="HTML")
        else:
            # Если медиафайлов нет и текущее сообщение текстовое - редактируем
            if current_is_text:
                try:
                    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
                    await cb.answer()
                    return
                except Exception:
                    pass

            # Если текущее сообщение медиа - удаляем и отправляем текстовое
            try:
                await cb.message.delete()
            except Exception:
                pass

            await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")

        await cb.answer()


@router.callback_query(F.data == "hwback")
async def hw_back(cb: CallbackQuery) -> None:
    async for db in get_session():
        from sqlalchemy import select

        res = await db.execute(select(User).where(User.telegram_id == cb.from_user.id))
        user = res.scalar_one_or_none()

        # Если пользователя нет, проверяем есть ли у него расписание (как в основной команде)
        if not user:
            from bot.database.models import ScheduleLesson
            # Пытаемся найти расписание по telegram_id через других пользователей
            # или создаем временного пользователя если есть расписание
            schedule_check = await db.execute(
                select(ScheduleLesson).limit(1)
            )
            has_any_schedule = schedule_check.scalar_one_or_none()

            if has_any_schedule:
                # Создаем временного пользователя для работы с расписанием
                temp_user = User(
                    telegram_id=cb.from_user.id,
                    username=f"temp_user_{cb.from_user.id}",
                    password="temp"
                )
                db.add(temp_user)
                await db.commit()
                await db.refresh(temp_user)
                user = temp_user
            else:
                await cb.answer("Пользователь не найден", show_alert=True)
                return

        items = await get_homeworks(db, user_id=user.id, only_active=True)
        if not items:
            # Определяем тип текущего сообщения и редактируем соответственно
            current_is_text = not (cb.message.photo or cb.message.video or cb.message.document)

            if current_is_text:
                await cb.message.edit_text("Активных домашних заданий нет.")
            else:
                # Если это медиа-сообщение, удаляем его и отправляем текстовое
                try:
                    await cb.message.delete()
                    await cb.message.answer("Активных домашних заданий нет.")
                except Exception:
                    # Если не получилось удалить, редактируем caption
                    await cb.message.edit_caption(caption="Активных домашних заданий нет.")

            await cb.answer()
            return

        # Получаем расписание для расчета дедлайнов (как в основной команде)
        from bot.database.models import ScheduleLesson
        from datetime import datetime

        now = datetime.now()
        current_weekday = now.isoweekday()  # 1=Monday, 7=Sunday

        # Получаем расписание пользователя
        schedule_lessons = (await db.execute(
            select(ScheduleLesson).where(ScheduleLesson.user_id == user.id)
        )).scalars().all()

        # Формируем кнопки для активных заданий
        kb_rows = []

        for h in items:
            # Рассчитываем дедлайн до следующего урока
            deadline_text = "—"
            if h.lesson:
                # Находим следующее занятие этого типа
                lesson_day = h.lesson.day_of_week  # 1-6 (Mon-Sat)
                lesson_start_time = h.lesson.start_time

                # Рассчитываем дни до следующего урока
                days_until = (lesson_day - current_weekday) % 7
                if days_until == 0:
                    # Сегодня - проверяем время
                    lesson_time = datetime.strptime(lesson_start_time, "%H:%M").time()
                    lesson_datetime = now.replace(hour=lesson_time.hour, minute=lesson_time.minute, second=0, microsecond=0)
                    if lesson_datetime <= now:
                        days_until = 7  # Следующая неделя

                if days_until == 0:
                    deadline_text = "Сегодня"
                elif days_until == 1:
                    deadline_text = "Завтра"
                else:
                    deadline_text = f"Через {days_until} дн."

            # Создаем красивое название с информацией об уроке и дедлайне
            lesson_info = ""
            if h.lesson:
                lesson_info = f"{h.lesson.course_code or h.lesson.title or 'Урок'} • "

            button_text = f"📝 {lesson_info}{h.subject}"
            if deadline_text != "—":
                button_text += f" ({deadline_text})"

            kb_rows.append([InlineKeyboardButton(text=button_text, callback_data=f"hw:{h.id}")])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

        active_count = len(items)
        stats_text = f"📝 Активных заданий: {active_count}"
        message_text = f"Ваши домашние задания:\n\n{stats_text}"

        # Определяем тип текущего сообщения и правильно его редактируем
        current_is_text = not (cb.message.photo or cb.message.video or cb.message.document)

        if current_is_text:
            # Если это текстовое сообщение - редактируем текст
            await cb.message.edit_text(message_text, reply_markup=kb)
        else:
            # Если это медиа-сообщение - удаляем его и отправляем текстовое
            try:
                await cb.message.delete()
                await cb.message.answer(message_text, reply_markup=kb)
            except Exception:
                # Если не получилось удалить, редактируем caption
                await cb.message.edit_caption(caption=message_text, reply_markup=kb)

        await cb.answer()


@router.callback_query(F.data.startswith("hwdone:"))
async def hw_done(cb: CallbackQuery) -> None:
    _, hw_id_str, revert_str = cb.data.split(":")
    hw_id = int(hw_id_str)
    revert = revert_str == "1"
    async for db in get_session():
        await update_homework_status(db, homework_id=hw_id, is_done=not revert)
    await cb.answer("Статус обновлён")

    # Обновляем отображение домашки после изменения статуса
    await hw_detail(cb)


# Ask-after-lesson callbacks
@router.callback_query(F.data.startswith("dz:"))
async def after_lesson_prompt(cb: CallbackQuery, state: FSMContext) -> None:
    _, lesson_id, answer = cb.data.split(":")
    if answer == "no":
        await cb.answer("Ок, домашки нет")
        await cb.message.edit_text("❌ Домашнего задания не было", reply_markup=None)
        return

    # Answer is yes -> start collecting homework
    await state.set_state(HomeworkState.collecting_homework)
    await state.update_data(
        lesson_id=lesson_id,
        homework_data={
            "texts": [],
            "media": []
        }
    )

    await cb.message.edit_text(
        "✅ Есть домашнее задание!\n\n"
        "📝 Отправьте текст, фото, файлы домашнего задания.\n"
        "📌 Когда закончите - отправьте команду /done",
        reply_markup=None
    )
    await cb.answer("Начинаю сбор домашнего задания")


# Команда /done должна быть ПЕРЕД обработчиком текста
@router.message(Command("done"), HomeworkState.collecting_homework)
async def finish_homework_collection(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    homework_data = data.get("homework_data", {"texts": [], "media": []})
    lesson_id_str = data.get("lesson_id", "test")  # Получаем lesson_id из состояния

    # Проверяем, что есть хоть что-то
    if not homework_data["texts"] and not homework_data["media"]:
        await message.answer("❌ Нет данных для сохранения! Отправьте текст или медиа, затем /done")
        return

    # Объединяем все тексты
    description = "\n\n".join(homework_data["texts"]) if homework_data["texts"] else "Домашнее задание"
    subject = "Домашнее задание"

    # Сохраняем в базу данных
    async for db in get_session():
        from sqlalchemy import select
        user = (await db.execute(select(User).where(User.telegram_id == message.from_user.id))).scalar_one_or_none()
        if not user:
            await message.answer("Сначала выполните /login")
            await state.clear()
            return

        # Если lesson_id не "test", пытаемся найти урок и связать с ним
        lesson_id = None
        calculated_deadline = None
        if lesson_id_str != "test":
            try:
                lesson_id = int(lesson_id_str)
                # Проверяем, что урок существует и принадлежит пользователю
                from bot.database.models import ScheduleLesson
                lesson = (await db.execute(
                    select(ScheduleLesson).where(
                        ScheduleLesson.id == lesson_id,
                        ScheduleLesson.user_id == user.id
                    )
                )).scalar_one_or_none()

                if lesson:
                    # Обновляем subject названием урока
                    subject = f"{lesson.course_code or lesson.title or 'Урок'}"

                    # Рассчитываем дедлайн до следующего урока
                    from bot.services.homeworks import calculate_deadline_from_lesson
                    calculated_deadline = await calculate_deadline_from_lesson(db, lesson_id)
                else:
                    lesson_id = None
            except (ValueError, TypeError):
                lesson_id = None

        await add_homework(
            db,
            user_id=user.id,
            subject=subject,
            description=description,
            deadline=calculated_deadline,  # Передаем рассчитанный дедлайн
            media_list=homework_data["media"],
            lesson_id=lesson_id  # Передаем lesson_id
        )

    # Показываем сводку
    summary = f"✅ Домашнее задание сохранено!"
    if lesson_id:
        summary += f"\n🎓 Связано с уроком: {subject}"
        if calculated_deadline:
            summary += f"\n⏰ Дедлайн: {calculated_deadline.strftime('%d.%m.%Y %H:%M')}"
    summary += "\n\n"
    if homework_data["texts"]:
        summary += f"📝 Текстов: {len(homework_data['texts'])}\n"
    if homework_data["media"]:
        summary += f"📎 Файлов: {len(homework_data['media'])}\n"

    await message.answer(summary)
    await state.clear()


# Collect homework content when in state (обработчик текста ПОСЛЕ команды /done)
@router.message(HomeworkState.collecting_homework, F.text)
async def collect_homework_text(message: Message, state: FSMContext) -> None:
    # Проверяем, что это не команда (на всякий случай)
    if message.text.startswith('/'):
        await message.answer("❓ Неизвестная команда. Отправьте текст домашнего задания или /done для завершения")
        return

    data = await state.get_data()
    homework_data = data.get("homework_data", {"texts": [], "media": []})

    homework_data["texts"].append(message.text)
    await state.update_data(homework_data=homework_data)

    await message.answer("✏️ Текст добавлен! Продолжайте отправлять материалы или /done для завершения")


@router.message(HomeworkState.collecting_homework, F.photo)
async def collect_homework_photo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    homework_data = data.get("homework_data", {"texts": [], "media": []})

    # Добавляем фото
    homework_data["media"].append(("photo", message.photo[-1].file_id))

    # Если есть подпись к фото, добавляем её как текст
    if message.caption:
        homework_data["texts"].append(message.caption)

    await state.update_data(homework_data=homework_data)
    await message.answer("📷 Фото добавлено! Продолжайте отправлять материалы или /done для завершения")


@router.message(HomeworkState.collecting_homework, F.document)
async def collect_homework_document(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    homework_data = data.get("homework_data", {"texts": [], "media": []})

    # Добавляем документ
    homework_data["media"].append(("document", message.document.file_id))

    # Если есть подпись к документу, добавляем её как текст
    if message.caption:
        homework_data["texts"].append(message.caption)

    await state.update_data(homework_data=homework_data)
    await message.answer("📎 Файл добавлен! Продолжайте отправлять материалы или /done для завершения")


@router.message(HomeworkState.collecting_homework, F.video)
async def collect_homework_video(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    homework_data = data.get("homework_data", {"texts": [], "media": []})

    # Добавляем видео
    homework_data["media"].append(("video", message.video.file_id))

    # Если есть подпись к видео, добавляем её как текст
    if message.caption:
        homework_data["texts"].append(message.caption)

    await state.update_data(homework_data=homework_data)
    await message.answer("🎥 Видео добавлено! Продолжайте отправлять материалы или /done для завершения")


# Обработчики для заголовков (просто игнорируем их)
@router.callback_query(F.data.startswith("hw_header_"))
async def hw_header_handler(cb: CallbackQuery) -> None:
    await cb.answer()

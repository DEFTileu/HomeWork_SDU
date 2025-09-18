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
        from datetime import datetime, timedelta
        import calendar

        now = datetime.now()
        current_weekday = now.isoweekday()  # 1=Monday, 7=Sunday

        # Получаем расписание пользователя
        schedule_lessons = (await db.execute(
            select(ScheduleLesson).where(ScheduleLesson.user_id == user.id)
        )).scalars().all()

        # ��ормируем кнопки для активных з��даний
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

        # Явно загружаем мед��афайлы с homework и используем unique() для устранения дубликатов
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
            f"Дедлайн: {hw.deadline if hw.deadline else '—'}\n"
            f"Статус: {'✅ Выполнено' if hw.is_done else '⏳ В процессе'}"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Сделано" if not hw.is_done else "↩️ Вернуть в работу", callback_data=f"hwdone:{hw.id}:{0 if not hw.is_done else 1}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="hwback")],
        ])

        # Проверяем, есть ли у сообщения медиафайлы
        if cb.message.photo or cb.message.video or cb.message.document:
            # Если это медиа-сообщение, редактируем caption
            try:
                await cb.message.edit_caption(caption=text, reply_markup=kb)
            except Exception:
                # Если не получилось отредактировать, отправляем новое
                if hw.media:
                    m = hw.media[0]
                    if m.file_type == "photo":
                        await cb.message.answer_photo(m.file_id, caption=text, reply_markup=kb)
                    elif m.file_type == "video":
                        await cb.message.answer_video(m.file_id, caption=text, reply_markup=kb)
                    else:
                        await cb.message.answer_document(m.file_id, caption=text, reply_markup=kb)
                else:
                    await cb.message.answer(text, reply_markup=kb)
        else:
            # Если это обычное текстовое сообщение, редактируем текст
            try:
                await cb.message.edit_text(text, reply_markup=kb)
            except Exception:
                # Если не получилось отредактировать, отправляем новое
                if hw.media:
                    m = hw.media[0]
                    if m.file_type == "photo":
                        await cb.message.answer_photo(m.file_id, caption=text, reply_markup=kb)
                    elif m.file_type == "video":
                        await cb.message.answer_video(m.file_id, caption=text, reply_markup=kb)
                    else:
                        await cb.message.answer_document(m.file_id, caption=text, reply_markup=kb)
                else:
                    await cb.message.answer(text, reply_markup=kb)

        await cb.answer()


@router.callback_query(F.data == "hwback")
async def hw_back(cb: CallbackQuery) -> None:
    await cb.message.delete()
    await list_homeworks(cb.message)
    await cb.answer()


@router.callback_query(F.data.startswith("hwdone:"))
async def hw_done(cb: CallbackQuery) -> None:
    _, hw_id_str, revert_str = cb.data.split(":")
    hw_id = int(hw_id_str)
    revert = revert_str == "1"
    async for db in get_session():
        await update_homework_status(db, homework_id=hw_id, is_done=not revert)
    await cb.answer("Статус обновлён")

    # Создаем новый callback с правильным форматом для hw_detail
    from types import SimpleNamespace
    new_cb = SimpleNamespace()
    new_cb.data = f"hw:{hw_id}"
    new_cb.from_user = cb.from_user
    new_cb.message = cb.message
    new_cb.answer = cb.answer

    await hw_detail(new_cb)


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

    # Объединяем все ��ексты
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

        # Если lesson_id не "test", п��таемся найти урок и связать с ним
        lesson_id = None
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
                else:
                    lesson_id = None
            except (ValueError, TypeError):
                lesson_id = None

        await add_homework(
            db,
            user_id=user.id,
            subject=subject,
            description=description,
            deadline=None,
            media_list=homework_data["media"],
            lesson_id=lesson_id  # Передаем lesson_id
        )

    # Показывае�� сводку
    summary = f"✅ Домашнее задание сохранено!"
    if lesson_id:
        summary += f"\n🎓 Связано с уроком: {subject}"
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
    # Проверяем, что это не команда (на всякий с��учай)
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

    # Если есть подпись к видео, доб��вляем её ка�� текст
    if message.caption:
        homework_data["texts"].append(message.caption)

    await state.update_data(homework_data=homework_data)
    await message.answer("🎥 Видео добавлено! Продолжайте отправлять материалы или /done для завершения")


# Обработчики для заголовков (просто игнорируем их)
@router.callback_query(F.data.startswith("hw_header_"))
async def hw_header_handler(cb: CallbackQuery) -> None:
    await cb.answer()

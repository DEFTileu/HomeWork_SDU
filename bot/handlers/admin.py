from __future__ import annotations
from functools import wraps

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ParseMode

from sqlalchemy import select, func, text

from bot.config import settings
from bot.database.session import get_session
from bot.database.models import User, Homework


router = Router(name="admin")


def _is_admin(message: Message) -> bool:
    """Проверяет, является ли пользователь администратором"""
    return bool(message.from_user and message.from_user.id in settings.ADMIN_IDS)


def admin_required(func):
    """Декоратор для проверки прав администратора"""
    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        if not _is_admin(message):
            await message.answer("❌ Недостаточно прав для выполнения этой команды")
            return
        return await func(message, *args, **kwargs)
    return wrapper


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message) -> None:
    """
    Отправка сообщения всем пользователям бота
    Использование: /broadcast <текст сообщения>
    """
    if not _is_admin(message):
        await message.answer("❌ Недостаточно прав для выполнения этой команды")
        return

    text_parts = message.text.split(maxsplit=1)
    if len(text_parts) < 2:
        await message.answer(
            "📢 <b>Массовая рассылка</b>\n\n"
            "Использование: <code>/broadcast &lt;текст сообщения&gt;</code>\n\n"
            "Пример: <code>/broadcast Важное объявление для всех студентов!</code>",
            parse_mode="HTML"
        )
        return

    broadcast_text = text_parts[1]

    async for db in get_session():
        users = (await db.execute(select(User).where(User.telegram_id.is_not(None)))).scalars().all()

        success_count = 0
        error_count = 0

        status_message = await message.answer("📤 Начинаю рассылку...")

        for user in users:
            try:
                await message.bot.send_message(user.telegram_id, broadcast_text)
                success_count += 1
            except Exception:
                error_count += 1

        result_text = (
            f"📊 <b>Результаты рассылки:</b>\n\n"
            f"✅ Успешно отправлено: {success_count}\n"
            f"❌ Ошибок: {error_count}\n"
            f"📈 Всего пользователей: {len(users)}"
        )

        await status_message.edit_text(result_text, parse_mode="HTML")


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    """Показывает подробную статистику использования бота"""
    if not _is_admin(message):
        await message.answer("❌ Недостаточно прав для выполнения этой команды")
        return

    async for db in get_session():
        # Основные счетчики
        users_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
        active_users = (await db.execute(
            select(func.count()).select_from(User).where(User.telegram_id.is_not(None))
        )).scalar_one()

        # Статистика домашних заданий
        total_homeworks = (await db.execute(select(func.count()).select_from(Homework))).scalar_one()
        active_homeworks = (await db.execute(
            select(func.count()).select_from(Homework).where(
                Homework.is_done.is_(False),
                Homework.is_archived.is_(False)
            )
        )).scalar_one()
        completed_homeworks = (await db.execute(
            select(func.count()).select_from(Homework).where(Homework.is_done.is_(True))
        )).scalar_one()
        archived_homeworks = (await db.execute(
            select(func.count()).select_from(Homework).where(Homework.is_archived.is_(True))
        )).scalar_one()

        # Статистика расписания
        from bot.database.models import ScheduleLesson
        schedule_lessons = (await db.execute(select(func.count()).select_from(ScheduleLesson))).scalar_one()

        stats_text = f"""
📊 <b>Статистика SDU Homework Bot</b>

👥 <b>Пользователи:</b>
• Всего зарегистрировано: {users_count}
• Активных (с Telegram ID): {active_users}

📝 <b>Домашние задания:</b>
• Всего создано: {total_homeworks}
• Активных: {active_homeworks}
• Выполнено: {completed_homeworks}
• В архиве: {archived_homeworks}

📅 <b>Расписание:</b>
• Всего занятий в базе: {schedule_lessons}

🔧 <b>Система:</b>
• Планировщик: Активен (проверки каждый час в XX:15)
• Архивация: Еженедельно по понедельникам в 02:00
• Напоминания: 20:00 ежедневно
"""

        await message.answer(stats_text, parse_mode="HTML")


@router.message(Command("thn"))
async def cmd_test_homework_now(message: Message) -> None:
    """
    Test Homework Now - тестовая команда для проверки системы напоминаний
    Симулирует окончание урока и проверяет работу уведомлений
    """
    if not _is_admin(message):
        await message.answer("❌ Недостаточно прав для выполнения это�� команды")
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from bot.services.reminder_after_lesson import unified_lesson_check

    await message.answer("🧪 <b>Тестирование системы напоминаний</b>\n\nЗапускаю проверки...", parse_mode="HTML")

    # 1. Тестовое сообщение с кнопками
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"dz:test:yes"),
                InlineKeyboardButton(text="❌ Нет", callback_data=f"dz:test:no"),
            ]
        ]
    )

    await message.answer(
        "🧪 <b>ТЕСТ:</b> Занятие 'TEST101 (Тестовая проверка) - T123' скоро закончится (через 5 минут).\n\n"
        "📝 Было ли домашнее задание?",
        reply_markup=kb,
        parse_mode="HTML"
    )

    # 2. Запуск функции проверки напоминаний
    try:
        await unified_lesson_check(message.bot)
        await message.answer("✅ <b>Тест завершен:</b> Функция unified_lesson_check выполнена успе��но", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ <b>Ошибка при тестировании:</b> {str(e)}", parse_mode="HTML")


@router.message(Command("sql"))
async def sql_for_admins(message: Message) -> None:
    """Выполнение SQL-запросов для администраторов"""
    if not _is_admin(message):
        await message.answer("❌ Недостаточно прав для выполнения этой команды")
        return

    # Извлекаем SQL-запрос из команды
    text_parts = message.text.split(maxsplit=1)
    if len(text_parts) < 2:
        await message.answer(
            "💾 <b>Выполнение SQL-запросов</b>\n\n"
            "Использование: <code>/sql &lt;SQL-запрос&gt;</code>\n\n"
            "Примеры:\n"
            "<code>/sql SELECT * FROM users LIMIT 5</code>\n"
            "<code>/sql SELECT COUNT(*) FROM homeworks</code>",
            parse_mode="HTML"
        )
        return

    query = text_parts[1].strip()

    async for db in get_session():
        try:
            # Выполняем SQL-запрос
            result = await db.execute(text(query))

            # Проверяем тип результата
            if query.upper().strip().startswith('SELECT'):
                # Для SELECT-запросов
                rows = result.fetchall()

                if not rows:
                    await message.answer("📄 Результатов не найде��о.")
                    return

                # Получаем заголовки столбцов
                headers = list(result.keys())

                # Формируем таблицу в формате Markdown
                table = "| " + " | ".join(headers) + " |\n"
                table += "|" + "|".join(["---" for _ in headers]) + "|\n"

                for row in rows:
                    row_data = [str(cell) if cell is not None else "NULL" for cell in row]
                    table += "| " + " | ".join(row_data) + " |\n"

                # Экранируем специальные символы Markdown
                special_chars = [
                    ('\\', '\\\\'),
                    ('*', '\\*'),
                    ('_', '\\_'),
                    ('[', '\\['),
                    (']', '\\]'),
                    ('(', '\\('),
                    (')', '\\)'),
                    ('~', '\\~'),
                    ('|', '\\|'),
                    ('-', '\\-'),
                    ('.', '\\.'),
                    ('>', '\\>')  # Добавляем экранирование символа >
                ]

                for char, replacement in special_chars:
                    table = table.replace(char, replacement)

                # Разделяем на части, если слишком длинная
                max_length = 4096
                if len(table) > max_length:
                    parts = []
                    while len(table) > max_length:
                        part = table[:max_length]
                        parts.append(part)
                        table = table[max_length:]

                    if table:
                        parts.append(table)

                    for i, part in enumerate(parts):
                        await message.answer(
                            f"📊 <b>Результат SQL-запроса (часть {i+1}/{len(parts)}):</b>\n\n"
                            f"```\n{part}\n```",
                            parse_mode=ParseMode.MARKDOWN_V2
                        )
                else:
                    await message.answer(
                        f"📊 <b>Результат SQL-запроса:</b>\n\n"
                        f"```\n{table}\n```",
                        parse_mode=ParseMode.MARKDOWN_V2
                    )
            else:
                # Для INSERT, UPDATE, DELETE запросов
                await db.commit()  # Подтверждаем изменения
                await message.answer(f"✅ <b>SQL-запрос выполнен успешно</b>\n\nЗатронуто строк: {result.rowcount}", parse_mode="HTML")

        except Exception as e:
            await message.answer(f"❌ <b>Ошибка при выполнении запроса:</b>\n\n<code>{str(e)}</code>", parse_mode="HTML")


@router.message(Command("help_admin"))
async def cmd_admin_help(message: Message) -> None:
    """Справка по админским командам"""
    if not _is_admin(message):
        return

    admin_help = """
👑 <b>Справка для администраторов</b>

📢 <b>/broadcast</b> &lt;текст&gt; - Массовая рассылка
   Отправляет сообщение всем пользователям бота
   
📊 <b>/stats</b> - Подробная статистика
   Показывает количество пользователей, заданий, расписание
   
🧪 <b>/thn</b> - Тест системы напоминаний
   Проверяет работу уведомлений о домашних заданиях

💾 <b>/sql</b> &lt;запрос&gt; - Выполнение SQL-запросов
   Позволяет выполнять прямые запросы к базе данных
   
🔧 <b>Техническая информация:</b>
• Планировщики работают каждый час в XX:15
• Архивация: понедельник 02:00
• Вечерние напоминания: ежедневно 20:00

ℹ️ <b>/help_admin</b> - Эта справка
"""

    await message.answer(admin_help, parse_mode="HTML")

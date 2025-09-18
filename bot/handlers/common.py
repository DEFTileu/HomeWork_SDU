from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.config import settings
from bot.database.session import get_session
from bot.services.commands import set_default_commands, set_admin_commands


router = Router(name="common")


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    """Обработчик команды /start с проверкой сессии"""
    user_name = message.from_user.first_name or "Пользователь"
    telegram_id = message.from_user.id

    async for db in get_session():
        from sqlalchemy import select
        from bot.database.models import User
        from bot.services.auth import is_session_active

        # Проверяем, есть ли пользователь в базе
        user = (await db.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()

        if user and not user.username.startswith('temp_user_') and user.password != 'temp':
            # Пользователь существует и имеет реальные учетные данные
            # Проверяем активность сессии
            session_active = await is_session_active(db, user)

            if not session_active:
                # Сессия истекла - просим переавторизации
                expired_text = f"""
🔒 <b>Сессия истекла, {user_name}!</b>

Ваша сессия в портале SDU больше не активна. 
Для продолжения работы необходимо войти в систему заново.

🔐 Выполните команду /login чтобы авторизоваться с вашими учетными данными SDU.

⚠️ До авторизации доступны только команды просмотра (/schedule, /homeworks).
Обновление расписания (/parse) будет недоступно.
"""
                await message.answer(expired_text, parse_mode="HTML")

                # Устанавливаем команды в зависимости от роли
                if telegram_id in settings.ADMIN_IDS:
                    await set_admin_commands(message.bot)
                else:
                    await set_default_commands(message.bot)
                return
            else:
                # Сессия активна - обычное приветствие
                welcome_text = f"""
🎓 С возвращением, {user_name}!

✅ Ваша сессия активна
👤 Аккаунт: {user.username}

Бот готов к работе! Используйте /help для просмотра команд.
"""
                await message.answer(welcome_text, parse_mode="HTML")
        else:
            # Пользователь новый или временный - обычное приветствие
            welcome_text = f"""
🎓 Добро пожаловать в SDU Homework Bot, {user_name}!

Этот бот поможет вам:
📝 Отслеживать домашние задания
📅 Просматривать расписание занятий  
⏰ Получать напоминания о дедлайнах
📚 Архивировать выполненные задания

Для полного функционала выполните /login чтобы войти в аккаунт SDU.

Используйте /help для просмотра всех доступных команд.
"""
            await message.answer(welcome_text, parse_mode="HTML")

    # Устанавливаем команды в зависимости от роли пользователя
    if telegram_id in settings.ADMIN_IDS:
        await set_admin_commands(message.bot)
    else:
        await set_default_commands(message.bot)


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    """Обработчик команды /help с подробной справкой"""
    user_id = message.from_user.id
    is_admin = user_id in settings.ADMIN_IDS

    help_text = """
🤖 <b>SDU Homework Bot - Справка по командам</b>

<b>📚 Основные команды:</b>
/start - 🚀 Запустить бота
/help - ❓ Показать эту справку
/login - 🔐 Войти в аккаунт SDU (необходимо для работы)

<b>📅 Расписание:</b>
/schedule - 📅 Посмотреть расписание занятий
/parse - 🔄 Обновить расписание с сайта SDU

<b>📝 Домашние задания:</b>
/homeworks - 📝 Список активных домашних заданий
/archive - 📚 Архив выполненных заданий

<b>🔔 Автоматические функции:</b>
• Напоминания о домашних заданиях за 5 минут до окончания урока
• Уведомления о предстоящих занятиях за 15 минут
• Ежедневные напоминания о невыполненных заданиях (20:00)
• Автоматическая архивация выполненных заданий

<b>📖 Как пользоваться:</b>
1. Выполните /login с вашими данными SDU
2. Загрузите расписание командой /parse
3. Бот автоматически будет спрашивать о домашних заданиях
4. Просматривайте задания через /homeworks
"""

    # Добавляем админские команды для администраторов
    if is_admin:
        admin_help = """

<b>👑 Команды администратора:</b>
/broadcast &lt;текст&gt; - 📢 Отправить сообщение всем пользователям
/stats - 📊 Статистика использования бота
/thn - 🧪 Тестировать систему напоминаний

<b>🛠 Техническая информация:</b>
• Планировщики работают в фоне каждый час в XX:15
• Архивация выполняется еженедельно по понедельникам
• Все данные сохраняются в зашифрованном виде
"""
        help_text += admin_help

    help_text += """

💡 <b>Подсказки:</b>
• Домашние задания автоматически связываются с уроками
• Дедлайны рассчитываются до следующего занятия
• Используйте кнопки для быстрого взаимодействия
• Все медиафайлы сохраняются вместе с заданиями

❓ <b>Проблемы?</b>
Если что-то не работает, попробуйте:
1. Выполнить /login заново
2. Обновить расписание через /parse
3. Перезапустить бота командой /start
"""

    await message.answer(help_text, parse_mode="HTML")


@router.message(Command("info"))
async def info_handler(message: Message) -> None:
    """Краткая информация о боте"""
    info_text = """
ℹ️ <b>SDU Homework Bot</b>

🎯 <b>Назначение:</b> Управление домашними заданиями и расписанием для студентов SDU

⚡ <b>Возможности:</b>
• Автоматические напоминания о домашних заданиях
• Синхронизация с расписанием SDU  
• Умные уведомления о предстоящих занятиях
• Архивирование выполненных заданий

🔧 <b>Технологии:</b> Python, aiogram, SQLAlchemy, APScheduler

📞 <b>Поддержка:</b> /help для подробной справки
"""

    await message.answer(info_text, parse_mode="HTML")

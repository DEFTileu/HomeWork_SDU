"""
Управление командами бота для пользователей и администраторов
"""
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from bot.config import settings


async def set_default_commands(bot: Bot):
    """Устанавливает команды для обычных пользователей"""
    commands = [
        BotCommand(command="/start", description="🚀 Запустить бота"),
        BotCommand(command="/help", description="❓ Помощь по командам"),
        BotCommand(command="/info", description="ℹ️ О боте"),
        BotCommand(command="/login", description="🔐 Войти в аккаунт SDU"),
        BotCommand(command="/schedule", description="📅 Посмотреть расписание"),
        BotCommand(command="/homeworks", description="📝 Список домашних заданий"),
        BotCommand(command="/parse", description="🔄 Обновить расписание с сайта"),
        BotCommand(command="/archive", description="📚 Архив выполненных заданий"),
    ]
    await bot.set_my_commands(commands=commands, scope=BotCommandScopeAllPrivateChats())


async def set_admin_commands(bot: Bot):
    """Устанавливает команды для администраторов"""
    admin_commands = [
        # Обычные команды пользователей
        BotCommand(command="/start", description="🚀 Запустить бота"),
        BotCommand(command="/help", description="❓ Помощь по командам"),
        BotCommand(command="/info", description="ℹ️ О боте"),
        BotCommand(command="/login", description="🔐 Войти в аккаунт SDU"),
        BotCommand(command="/schedule", description="📅 Посмотреть расписание"),
        BotCommand(command="/homeworks", description="📝 Список домашних заданий"),
        BotCommand(command="/parse", description="🔄 Обновить расписание с сайта"),
        BotCommand(command="/archive", description="📚 Архив выполненных заданий"),
        # Админские команды
        BotCommand(command="/broadcast", description="📢 Отправить сообщение всем"),
        BotCommand(command="/stats", description="📊 Статистика бота"),
        BotCommand(command="/thn", description="🧪 Тест системы напоминаний"),
        BotCommand(command="/sql", description="💾 Выполнить SQL-запрос"),
        BotCommand(command="/help_admin", description="👑 Справка для админов"),
    ]

    # Устанавливаем команды для каждого админа
    for admin_id in settings.ADMIN_IDS:
        await bot.set_my_commands(commands=admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))


async def set_start_commands(bot: Bot, user_id: int):
    """Устанавливает минимальный набор команд для нового пользователя"""
    commands = [
        BotCommand(command="/start", description="🚀 Запустить бота"),
        BotCommand(command="/help", description="❓ Помощь по командам"),
    ]
    await bot.set_my_commands(commands=commands, scope=BotCommandScopeChat(chat_id=user_id))

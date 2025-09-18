import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums.parse_mode import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

# Опциональный импорт dotenv для локальной разработки
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv не обязателен в production (Railway использует переменные окружения напрямую)
    pass

from bot.config import settings
from bot.database.session import init_models
from bot.handlers.auth import router as auth_router
from bot.handlers.common import router as common_router
from bot.handlers.homeworks import router as homeworks_router
from bot.handlers.reminders import router as reminders_router
from bot.handlers.archive import router as archive_router
from bot.handlers.schedule import router as schedule_router
from bot.handlers.admin import router as admin_router
from bot.services.scheduler import build_scheduler, setup_jobs, schedule_deadline_reminders
from bot.services.commands import set_default_commands, set_admin_commands


async def on_startup(bot: Bot) -> None:
    """Действия при запуске бота"""
    # Инициализация базы данных
    await init_models()

    # Установка команд для пользователей и администраторов
    await set_default_commands(bot)
    await set_admin_commands(bot)

    logging.info("✅ Бот успешно запущен!")
    logging.info(f"📊 Администраторы: {settings.ADMIN_IDS}")


async def main() -> None:
    """Главная функция запуска бота"""
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    token = settings.BOT_TOKEN
    if not token:
        raise RuntimeError("❌ BOT_TOKEN не установлен в переменных окружения")

    # Создание бота и диспетчера
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Подключение роутеров в правильном порядке
    dp.include_router(common_router)  # Общие команды (start, help)
    dp.include_router(auth_router)    # Авторизация (login)
    dp.include_router(schedule_router)  # Расписание (schedule, parse)
    dp.include_router(homeworks_router)  # Домашние задания (homeworks)
    dp.include_router(archive_router)   # Архив (archive)
    dp.include_router(reminders_router) # Напоминания
    dp.include_router(admin_router)     # Админские команды (broadcast, stats, thn)

    # Инициализация при запуске
    await on_startup(bot)

    # Настройка планировщика задач
    scheduler = build_scheduler()
    setup_jobs(bot, scheduler)
    await schedule_deadline_reminders(bot, scheduler)
    scheduler.start()

    logging.info("🚀 Запуск polling...")

    # Запуск бота
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logging.info("⏹️ Бот остановлен пользователем")
    finally:
        scheduler.shutdown()
        logging.info("📴 Планировщик остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот завершил работу")

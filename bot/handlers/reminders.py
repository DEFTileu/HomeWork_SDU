from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message


router = Router(name="reminders")


@router.message(Command("reminders"))
async def list_reminders(message: Message) -> None:
    await message.answer("Напоминания (заглушка).")



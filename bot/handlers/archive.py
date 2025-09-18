from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from sqlalchemy import select

from bot.database.session import get_session
from bot.database.models import User
from bot.services.archive import get_archive_by_week


router = Router(name="archive")


def _kb_for_week(weeks_ago: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"archnav:{weeks_ago+1}"), InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"archnav:{max(weeks_ago-1, 0)}")],
        ]
    )


@router.message(Command("archive"))
async def cmd_archive(message: Message) -> None:
    await show_archive(message, weeks_ago=0)


async def show_archive(message_or_cb, weeks_ago: int) -> None:
    async for db in get_session():
        res = await db.execute(select(User).where(User.telegram_id == message_or_cb.from_user.id))
        user = res.scalar_one_or_none()
        if not user:
            if isinstance(message_or_cb, Message):
                await message_or_cb.answer("Сначала выполните /login")
            else:
                await message_or_cb.answer("Сначала выполните /login", show_alert=True)
            return
        items = await get_archive_by_week(db, user.id, weeks_ago=weeks_ago)
        if not items:
            text = "Архив пуст за выбранную неделю."
        else:
            lines = [f"• {i.subject} — выполнено {i.done_at.date() if i.done_at else 'ранее'}" for i in items]
            text = "\n".join(lines)

        kb = _kb_for_week(weeks_ago)
        if isinstance(message_or_cb, Message):
            await message_or_cb.answer(text or "Архив пуст", reply_markup=kb)
        else:
            # Avoid editing with same content
            current = message_or_cb.message.text or ""
            new_text = text or "Архив пуст"
            if current == new_text:
                await message_or_cb.answer()
                return
            await message_or_cb.message.edit_text(new_text, reply_markup=kb)
            await message_or_cb.answer()


@router.callback_query(F.data.startswith("archnav:"))
async def archive_nav(cb: CallbackQuery) -> None:
    weeks_ago = int(cb.data.split(":", 1)[1])
    await show_archive(cb, weeks_ago=weeks_ago)



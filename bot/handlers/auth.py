from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.database.session import get_session
from bot.services.auth import verify_sdu_credentials, create_or_update_user, save_user_session
from bot.services.schedule import fetch_and_import_schedule, fetch_and_import_schedule_new

router = Router(name="auth")


class LoginStates(StatesGroup):
    waiting_username = State()
    waiting_password = State()


@router.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext) -> None:
    await state.set_state(LoginStates.waiting_username)
    await message.answer("Введите ваш username портала SDU:")


@router.message(LoginStates.waiting_username)
async def process_username(message: Message, state: FSMContext) -> None:
    await state.update_data(username=message.text.strip())
    await state.set_state(LoginStates.waiting_password)
    await message.answer("Теперь введите пароль:")


@router.message(LoginStates.waiting_password)
async def process_password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    username = data.get("username")
    password = message.text

    if not username or not password:
        await message.answer("Некорректные данные. Попробуйте /login ещё раз.")
        await state.clear()
        return

    ok, sess = await verify_sdu_credentials(username, password)
    if not ok:
        await message.answer("Неверный логин или пароль. Попробуйте снова: /login")
        await state.clear()
        return

    async for db in get_session():
        user = await create_or_update_user(db, telegram_id=message.from_user.id, username=username, password=password)
        await save_user_session(db, user, sess)
        # Fetch schedule right after successful login
        try:
            imported = await fetch_and_import_schedule_new(db, user.id, session_payload=sess)
            await message.answer(f"Вы успешно вошли! ✅\nИмпортировано занятий: {imported}")
        except Exception:
            await message.answer("Вы успешно вошли! ✅")
    await state.clear()



from __future__ import annotations

import json
from typing import Optional, Tuple
import logging

import aiohttp
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fake_useragent import UserAgent

from bot.config import settings
from bot.database.models import User, UserSession
from bs4 import BeautifulSoup as BS

# Константы для логина
LOGIN_URL = settings.SDU_LOGIN_URL
login_data_template = {
    'username': '',
    'password': '',
    'modstring': '',
    'LogIn': 'Log in'
}

async def login_user(username: str, password: str, session: aiohttp.ClientSession = None) -> bool:
    login_data = login_data_template.copy()
    login_data['username'] = username
    login_data['password'] = password

    if session is None:
        HEADERS = {'User-Agent': UserAgent().random}
        async with aiohttp.ClientSession(headers=HEADERS) as new_session:
            return await _perform_login(new_session, login_data)
    else:
        return await _perform_login(session, login_data)

async def _perform_login(session: aiohttp.ClientSession, login_data: dict) -> bool:
    async with session.post(LOGIN_URL, data=login_data, ssl=False) as response:
        if response.status != 200:
            return False
        text = await response.text()

        soup = BS(text, 'lxml')
        if soup.find("a", {"class": "loginLink"}):
            return False
    return True

async def verify_sdu_credentials(username: str, password: str) -> Tuple[bool, dict]:
    """Обновленная функция для проверки учетных данных SDU"""
    HEADERS = {'User-Agent': UserAgent().random}
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        try:
            # Используем новую функцию логина
            login_success = await login_user(username, password, session)

            if not login_success:
                return False, {}

            # Собираем cookies после успешного логина
            cookies = {c.key: c.value for c in session.cookie_jar}

            if settings.DEBUG:
                logging.debug(f"SDU login success={login_success} cookies_keys={list(cookies.keys())}")

            return True, {"cookies": cookies}
        except Exception:
            if settings.DEBUG:
                logging.exception("SDU login request failed")
            return False, {}


async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    stmt = select(User).where(User.username == username)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def get_user_by_telegram_id(db: AsyncSession, telegram_id: int) -> Optional[User]:
    stmt = select(User).where(User.telegram_id == telegram_id)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def create_or_update_user(db: AsyncSession, telegram_id: int, username: str, password: str) -> User:
    user = await get_user_by_username(db, username)
    if user:
        user.telegram_id = telegram_id
        user.password = password
    else:
        user = User(telegram_id=telegram_id, username=username, password=password)
        db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def save_user_session(db: AsyncSession, user: User, session_payload: dict) -> UserSession:
    cookies = session_payload.get("cookies")
    data = session_payload.get("data") or {}
    access_token = data.get("access_token") or data.get("token")
    refresh_token = data.get("refresh_token")

    await db.execute(delete(UserSession).where(UserSession.user_id == user.id))

    us = UserSession(
        user_id=user.id,
        access_token=access_token,
        refresh_token=refresh_token,
        cookies_json=json.dumps(cookies) if cookies else None,
        expires_at=None,
    )
    db.add(us)
    await db.commit()
    await db.refresh(us)
    return us


async def is_session_active(db: AsyncSession, user: User) -> bool:
    sess = (await db.execute(select(UserSession).where(UserSession.user_id == user.id))).scalar_one_or_none()
    if not sess:
        return False
    # Simple ping to a protected page
    cookies = {}
    try:
        if sess.cookies_json:
            cookies = json.loads(sess.cookies_json)
    except Exception:
        cookies = {}
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://my.sdu.edu.kz/index.php?mod=schedule", cookies=cookies, allow_redirects=False) as resp:
                return resp.status in (200, 302)
    except Exception:
        return False

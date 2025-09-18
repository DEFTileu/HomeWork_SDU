from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

from bot.config import settings
from bot.database.models import User, Homework
from bot.services.reminder_after_lesson import unified_lesson_check
from bot.services.archive import move_done_homeworks_to_archive
from bot.database.session import get_session


def build_scheduler() -> AsyncIOScheduler:
    tz = ZoneInfo(settings.TIMEZONE)
    return AsyncIOScheduler(timezone=tz)


async def notify_evening(bot: Bot) -> None:
    async for db in get_session():
        users = (await db.execute(select(User))).scalars().all()
        for user in users:
            pending = (await db.execute(
                select(Homework).where(Homework.user_id == user.id, Homework.is_done.is_(False))
            )).scalars().all()
            if pending:
                try:
                    await bot.send_message(user.telegram_id, f"Напоминание: у вас {len(pending)} незавершённых домашних. Откройте /homeworks")
                except Exception:
                    pass


async def schedule_deadline_reminders(bot: Bot, scheduler: AsyncIOScheduler) -> None:
    tz = ZoneInfo(settings.TIMEZONE)
    now = datetime.now(tz)
    async for db in get_session():
        hws = (await db.execute(select(Homework).where(Homework.is_done.is_(False)))).scalars().all()
        for hw in hws:
            if not hw.deadline:
                continue
            # -5 hours
            remind_5h = hw.deadline - timedelta(hours=5)
            if remind_5h > now:
                scheduler.add_job(
                    send_hw_reminder,
                    trigger=DateTrigger(remind_5h),
                    args=[bot, hw.id, "Сделай домашку (до дедлайна 5 часов)"],
                    id=f"hw5h-{hw.id}",
                    replace_existing=True,
                )
            # -10 minutes
            remind_10m = hw.deadline - timedelta(minutes=10)
            if remind_10m > now:
                scheduler.add_job(
                    send_hw_reminder,
                    trigger=DateTrigger(remind_10m),
                    args=[bot, hw.id, "Урок скоро, молодец если сделал"],
                    id=f"hw10m-{hw.id}",
                    replace_existing=True,
                )


async def send_hw_reminder(bot: Bot, homework_id: int, text: str) -> None:
    async for db in get_session():
        from sqlalchemy.orm import joinedload
        hw = (
            await db.execute(
                select(Homework)
                .options(joinedload(Homework.user))
                .where(Homework.id == homework_id, Homework.is_done.is_(False))
            )
        ).scalars().one_or_none()
        if not hw or not hw.user or not hw.user.telegram_id:
            return
        try:
            await bot.send_message(hw.user.telegram_id, f"[{hw.subject}] {text}")
        except Exception:
            pass


def setup_jobs(bot: Bot, scheduler: AsyncIOScheduler) -> None:
    # 20:00 daily
    scheduler.add_job(notify_evening, trigger=CronTrigger(hour=20, minute=0), args=[bot], id="evening-digest", replace_existing=True)
    # weekly archive job: every Monday at 02:00
    scheduler.add_job(archive_weekly_job, trigger=CronTrigger(day_of_week="mon", hour=2, minute=0), args=[bot], id="weekly-archive", replace_existing=True)
    # Unified lesson check: homework questions + upcoming lesson reminders at XX:15 every hour
    scheduler.add_job(unified_lesson_check, trigger=CronTrigger(minute=15), args=[bot], id="unified-lesson-check", replace_existing=True)


async def archive_weekly_job(bot: Bot) -> None:
    async for db in get_session():
        try:
            count = await move_done_homeworks_to_archive(db)
        except Exception:
            count = 0

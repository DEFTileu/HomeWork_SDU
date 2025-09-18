from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Boolean, Text, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    homeworks: Mapped[list["Homework"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    lessons: Mapped[list["ScheduleLesson"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def __str__(self) -> str:
        return f"User(id={self.id}, username={self.username!r}, telegram_id={self.telegram_id})"


class Homework(Base):
    __tablename__ = "homeworks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("schedule_lessons.id", ondelete="SET NULL"), nullable=True, index=True)  # Связь с уроком
    subject: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text())
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)  # Вместо удаления - архивация
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="homeworks")
    lesson: Mapped["ScheduleLesson | None"] = relationship()  # Связь с уроком
    media: Mapped[list["HomeworkMedia"]] = relationship(back_populates="homework", cascade="all, delete-orphan")

    def __str__(self) -> str:
        status = "done" if self.is_done else "pending"
        dl = self.deadline.isoformat() if self.deadline else None
        return f"Homework(id={self.id}, subject={self.subject!r}, status={status}, deadline={dl})"


class HomeworkMedia(Base):
    __tablename__ = "homework_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    homework_id: Mapped[int] = mapped_column(ForeignKey("homeworks.id", ondelete="CASCADE"), index=True)
    file_type: Mapped[str] = mapped_column(String(20))  # photo, video, document
    file_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    homework: Mapped[Homework] = relationship(back_populates="media")

    def __str__(self) -> str:
        return f"HomeworkMedia(id={self.id}, homework_id={self.homework_id}, file_type={self.file_type!r})"


class HomeworkArchive(Base):
    __tablename__ = "homework_archive"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    subject: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str] = mapped_column(Text())
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, index=True)

    def __str__(self) -> str:
        dl = self.deadline.isoformat() if self.deadline else None
        da = self.done_at.isoformat() if self.done_at else None
        return f"HomeworkArchive(id={self.id}, subject={self.subject!r}, deadline={dl}, done_at={da}, archived_at={self.archived_at.isoformat()})"


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    access_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cookies_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    def __str__(self) -> str:
        exp = self.expires_at.isoformat() if self.expires_at else None
        return f"UserSession(id={self.id}, user_id={self.user_id}, expires_at={exp})"


class ScheduleLesson(Base):
    __tablename__ = "schedule_lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, index=True)  # 1=Mon..6=Sat
    start_time: Mapped[str] = mapped_column(String(16))
    end_time: Mapped[str] = mapped_column(String(16))
    course_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lesson_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    section_code: Mapped[str | None] = mapped_column(String(16), nullable=True)  # [03-N], [14-P], etc
    teacher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    room: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    user: Mapped[User] = relationship(back_populates="lessons")

    def __str__(self) -> str:
        title = self.title or self.course_code or "Lesson"
        return f"ScheduleLesson(id={self.id}, day={self.day_of_week}, time={self.start_time}-{self.end_time}, title={title!r}, room={self.room!r})"

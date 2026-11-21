"""Все таблицы базы данных в одном месте (стиль SQLAlchemy 2.0).
Каждый класс - это таблица, каждый атрибут Mapped[...] - это столбец.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base

def _now() -> datetime:
    return datetime.now()


# ------------------------------------настройки
class Setting(Base):
    """Простое хранилище "ключ - значение" (тема, выбранная папка, время простоя и т.д.)."""
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


# ------------------------------------ сортировка
class SortRule(Base):
    """Правило сортировки: ключевые слова в имени и/или расширения -> папка."""
    __tablename__ = "sort_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    keywords: Mapped[str] = mapped_column(String(300), default="")      # "домашка, дз, homework"
    extensions: Mapped[str] = mapped_column(String(300), default="")    # ".pdf, .docx"
    target_folder: Mapped[str] = mapped_column(String(200))             # "Учёба/Домашние задания"
    priority: Mapped[int] = mapped_column(Integer, default=0)           # чем больше, тем раньше проверяется
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SortLog(Base):
    """Журнал перемещений: по нему работает кнопка "Отменить"."""
    __tablename__ = "sort_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_name: Mapped[str] = mapped_column(String(300))
    original_path: Mapped[str] = mapped_column(Text)
    new_path: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(200), default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)


# -------------------------------------------------------------------- таймер
class StudySession(Base):
    """Одна сессия учёбы/работы, засечённая таймером (или добавленная вручную)."""
    __tablename__ = "study_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(100), default="")
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    duration_seconds: Mapped[int] = mapped_column(Integer)


# --------------------------------------------------------- трекер приложений
class TrackedApp(Base):
    """Программа, которую пользователь разрешил отслеживать."""
    __tablename__ = "tracked_apps"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_name: Mapped[str] = mapped_column(String(200), unique=True)  # "chrome.exe" (строчными)
    display_name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class AppSession(Base):
    """Один записанный отрезок времени, когда программа была на переднем плане."""
    __tablename__ = "app_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # ondelete="CASCADE": удалили программу из списка - удалилась и её история
    app_id: Mapped[int] = mapped_column(ForeignKey("tracked_apps.id", ondelete="CASCADE"))
    start_time: Mapped[datetime] = mapped_column(DateTime, index=True)   # индекс ускоряет выборку по датам
    end_time: Mapped[datetime] = mapped_column(DateTime)
    duration_seconds: Mapped[int] = mapped_column(Integer)


# -------------------------------------------------------------------- списки
class MediaItem(Base):
    """Аниме, манга, книги и фильмы лежат в одной таблице, различаются полем type."""
    __tablename__ = "media_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20), index=True)       # anime / manga / book / film
    title: Mapped[str] = mapped_column(String(300), index=True)
    status: Mapped[str] = mapped_column(String(20), default="planned")
    progress: Mapped[int] = mapped_column(Integer, default=0)       # серии / главы / страницы / части
    total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # от 0 до 10
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ------------------------------------------------------------------- пароли
class VaultMeta(Base):
    """Соль и зашифрованное проверочное значение. Сам мастер-пароль нигде не хранится."""
    __tablename__ = "vault_meta"

    id: Mapped[int] = mapped_column(primary_key=True)
    salt: Mapped[bytes] = mapped_column(LargeBinary)
    verifier: Mapped[bytes] = mapped_column(LargeBinary)


class Credential(Base):
    """Одна запись хранилища: сайт, логин и ЗАШИФРОВАННЫЙ пароль."""
    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(primary_key=True)
    site: Mapped[str] = mapped_column(String(300), index=True)
    username: Mapped[str] = mapped_column(String(300), default="")
    encrypted_password: Mapped[bytes] = mapped_column(LargeBinary)   # токен Fernet
    notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

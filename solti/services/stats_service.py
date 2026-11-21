"""Запросы, которые превращают записанное время в цифры для графиков и итогов."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Optional
from sqlalchemy import func, select   # func.sum / func.date - SQL-функции СУММА и ДАТА
from ..database.base import session_scope
from ..database.models import AppSession, StudySession, TrackedApp

@dataclass(frozen=True)
class UsageSummary:
    """Итоги за период для строки над графиками."""
    total_seconds: int
    daily_average_seconds: int
    most_used_app: Optional[str]
    most_used_seconds: int
    app_count: int

def range_for_days(days: int, today: Optional[date] = None) -> tuple[datetime, datetime]:
    """Начало и конец периода. days=1 -> только сегодня; days=7 -> сегодня и 6 дней до него."""
    today = today or date.today()
    start = datetime.combine(today - timedelta(days=days - 1), time.min)
    end = datetime.combine(today + timedelta(days=1), time.min)
    return start, end

def usage_per_app(start: datetime, end: datetime) -> list[tuple[str, int]]:
    """[(название программы, секунды)], от самой используемой к наименее."""
    with session_scope() as s:
        rows = s.execute(
            select(TrackedApp.display_name, func.sum(AppSession.duration_seconds).label("total"))
            .join(TrackedApp, TrackedApp.id == AppSession.app_id)
            .where(AppSession.start_time >= start, AppSession.start_time < end)
            .group_by(TrackedApp.id)
            .order_by(func.sum(AppSession.duration_seconds).desc())
        ).all()
    return [(name, int(total or 0)) for name, total in rows]


def usage_per_day(start: datetime, end: datetime) -> list[tuple[date, int]]:
    """Время за КАЖДЫЙ день периода (0, если в этот день ничего не записано)."""
    with session_scope() as s:
        rows = s.execute(
            select(func.date(AppSession.start_time), func.sum(AppSession.duration_seconds))
            .where(AppSession.start_time >= start, AppSession.start_time < end)
            .group_by(func.date(AppSession.start_time))
        ).all()
    seconds_by_day = {date.fromisoformat(str(day)): int(total or 0) for day, total in rows}

    # Дни без записей база не вернёт, поэтому дополняем их нулями сами
    day_count = (end.date() - start.date()).days
    result = []
    for offset in range(day_count):
        day = start.date() + timedelta(days=offset)
        result.append((day, seconds_by_day.get(day, 0)))
    return result


def summary(start: datetime, end: datetime) -> UsageSummary:
    """Всего, в среднем за день, самая используемая программа и сколько всего программ."""
    per_app = usage_per_app(start, end)
    total = sum(seconds for _, seconds in per_app)
    days = max(1, (end.date() - start.date()).days)
    if per_app:
        top_name, top_seconds = per_app[0]
    else:
        top_name, top_seconds = None, 0
    return UsageSummary(total, total // days, top_name, top_seconds, len(per_app))


def apps_between(start: datetime, end: datetime, limit: int = 3) -> list[tuple[str, int]]:
    """Какие программы использовались в этот промежуток (показываем после сессии таймера)."""
    with session_scope() as s:
        rows = s.execute(
            select(TrackedApp.display_name, func.sum(AppSession.duration_seconds))
            .join(TrackedApp, TrackedApp.id == AppSession.app_id)
            .where(AppSession.end_time >= start, AppSession.start_time <= end)
            .group_by(TrackedApp.id)
            .order_by(func.sum(AppSession.duration_seconds).desc())
            .limit(limit)
        ).all()
    return [(name, int(total or 0)) for name, total in rows]


def study_per_category(start: datetime, end: datetime) -> list[tuple[str, int]]:
    """Сколько времени таймера ушло на каждую категорию."""
    with session_scope() as s:
        rows = s.execute(
            select(StudySession.category, func.sum(StudySession.duration_seconds))
            .where(StudySession.start_time >= start, StudySession.start_time < end)
            .group_by(StudySession.category)
            .order_by(func.sum(StudySession.duration_seconds).desc())
        ).all()
    return [((category or "Другое"), int(total or 0)) for category, total in rows]


def format_duration(seconds: int) -> str:
    """Секунды в понятный текст: 3725 -> '1 ч 02 мин', 540 -> '9 мин', 20 -> '20 с'."""
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} ч {minutes:02d} мин"
    if minutes:
        return f"{minutes} мин"
    return f"{secs} с"

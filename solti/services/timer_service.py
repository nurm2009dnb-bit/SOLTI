"""
Таймер учёбы: старт / стоп, история сессий и необязательная цель.
Сам секундомер живёт в памяти, а в базу сессия попадает, когда нажимают "Стоп".
"""
from __future__ import annotations
from datetime import date, datetime, time, timedelta
from typing import Optional
from sqlalchemy import func, select
from ..database.base import session_scope
from ..database.models import StudySession

DEFAULT_CATEGORIES = ["Программирование", "Учёба", "Чтение", "Проект", "Другое"]

# Сессии короче этого считаем случайным нажатием и не сохраняем
MIN_SESSION_SECONDS = 15

class StudyTimer:
    """Секундомер. Время начала хранится в _start; None значит "таймер не идёт"."""

    def __init__(self) -> None:
        self._start: Optional[datetime] = None
        self.title = ""
        self.category = ""
        self.goal_seconds: Optional[int] = None

    @property
    def is_running(self) -> bool:
        return self._start is not None

    @property
    def started_at(self) -> Optional[datetime]:
        return self._start

    # Параметр now есть почти у всех методов - тесты передают туда своё время,
    # чтобы не ждать по-настоящему 25 минут.
    def start(self, title: str, category: str, goal_minutes: Optional[int] = None,
              now: Optional[datetime] = None) -> None:
        if self.is_running:
            raise RuntimeError("Таймер уже запущен.")
        title = title.strip()
        if not title:
            raise ValueError("Напишите, над чем вы работаете.")
        if goal_minutes is not None and goal_minutes <= 0:
            raise ValueError("Цель должна быть положительным числом минут.")
        self.title = title
        self.category = category.strip()
        self.goal_seconds = goal_minutes * 60 if goal_minutes else None
        self._start = now or datetime.now()

    def elapsed_seconds(self, now: Optional[datetime] = None) -> int:
        if self._start is None:
            return 0
        passed = (now or datetime.now()) - self._start
        return max(0, int(passed.total_seconds()))

    def goal_reached(self, now: Optional[datetime] = None) -> bool:
        return self.goal_seconds is not None and self.elapsed_seconds(now) >= self.goal_seconds

    def stop(self, now: Optional[datetime] = None) -> Optional[StudySession]:
        """Останавливает таймер и сохраняет сессию. Слишком короткие сессии не сохраняются."""
        if self._start is None:
            return None
        end = now or datetime.now()
        start, title, category = self._start, self.title, self.category
        self._start = None

        seconds = int((end - start).total_seconds())
        if seconds < MIN_SESSION_SECONDS:
            return None

        with session_scope() as s:
            session_row = StudySession(title=title, category=category, start_time=start,
                                       end_time=end, duration_seconds=seconds)
            s.add(session_row)
            s.flush()
            return session_row


# ------------------------------------------------------------- история сессий
def add_manual_session(title: str, category: str, minutes: int, day: Optional[date] = None) -> int:
    """Добавить сессию, которую забыли засечь. Ставим её на полдень выбранного дня."""
    if not title.strip():
        raise ValueError("Напишите, над чем вы работали.")
    if minutes <= 0:
        raise ValueError("Количество минут должно быть больше нуля.")
    day = day or date.today()
    start = datetime.combine(day, time(12, 0))
    with session_scope() as s:
        session_row = StudySession(title=title.strip(), category=category.strip(), start_time=start,
                                   end_time=start + timedelta(minutes=minutes), duration_seconds=minutes * 60)
        s.add(session_row)
        s.flush()
        return session_row.id


def recent_sessions(limit: int = 100) -> list[StudySession]:
    with session_scope() as s:
        return list(s.scalars(select(StudySession).order_by(StudySession.start_time.desc()).limit(limit)).all())


def delete_session(session_id: int) -> None:
    with session_scope() as s:
        session_row = s.get(StudySession, session_id)
        if session_row is not None:
            s.delete(session_row)


def total_seconds(start: datetime, end: datetime) -> int:
    """Сколько всего секунд таймера за период. coalesce(..., 0) - вернуть 0, если сессий нет."""
    with session_scope() as s:
        total = s.scalar(
            select(func.coalesce(func.sum(StudySession.duration_seconds), 0))
            .where(StudySession.start_time >= start, StudySession.start_time < end)
        )
        return int(total or 0)

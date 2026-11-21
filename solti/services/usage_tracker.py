"""Считает, сколько времени каждая *разрешённая* программа была на переднем плане.

Как это работает:
  * фоновый поток каждые несколько секунд спрашивает: какая программа сейчас активна?
  * если она есть в списке отслеживаемых (и включена), время идёт в текущий "отрезок"
  * отрезок сохраняется в базу, когда программа сменилась, когда пользователь отошёл,
    и не реже раза в минуту (если программа упадёт, почти ничего не потеряется)
  * если мышь и клавиатура не трогались idle_limit секунд, время НЕ считается

Вся логика лежит в tick(), а время передаётся в неё параметром. Поэтому её можно
проверить тестами мгновенно, без реального ожидания. Поток просто вызывает tick() в цикле.
"""
from __future__ import annotations

import logging     # запись событий и ошибок в файл журнала solti.log
import threading   # фоновый поток, чтобы окно не зависало во время слежения
from datetime import datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import select

from .. import config
from ..database.base import session_scope
from ..database.models import AppSession, TrackedApp
from . import system_info

log = logging.getLogger(__name__)


# ------------------------------------------------------- список отслеживаемых программ
def pretty_name(process_name: str) -> str:
    """'visual_studio.exe' -> 'Visual Studio' - красивое имя по умолчанию."""
    base = process_name[:-4] if process_name.lower().endswith(".exe") else process_name
    return base.replace("_", " ").replace("-", " ").title()


def list_tracked_apps() -> list[TrackedApp]:
    with session_scope() as s:
        return list(s.scalars(select(TrackedApp).order_by(TrackedApp.display_name)).all())


def add_tracked_app(process_name: str, display_name: str = "") -> int:
    process_name = process_name.strip().lower()
    if not process_name:
        raise ValueError("Укажите имя процесса (например: code.exe).")
    with session_scope() as s:
        existing = s.scalar(select(TrackedApp).where(TrackedApp.process_name == process_name))
        if existing is not None:
            raise ValueError(f"{existing.display_name} уже есть в списке.")
        app = TrackedApp(process_name=process_name,
                         display_name=display_name.strip() or pretty_name(process_name),
                         enabled=True)
        s.add(app)
        s.flush()
        return app.id


def set_app_enabled(app_id: int, enabled: bool) -> None:
    with session_scope() as s:
        app = s.get(TrackedApp, app_id)
        if app is not None:
            app.enabled = enabled


def rename_app(app_id: int, display_name: str) -> None:
    if not display_name.strip():
        raise ValueError("Название не может быть пустым.")
    with session_scope() as s:
        app = s.get(TrackedApp, app_id)
        if app is not None:
            app.display_name = display_name.strip()


def remove_tracked_app(app_id: int) -> None:
    """Удаляет программу ВМЕСТЕ с её историей (за это отвечает ON DELETE CASCADE в базе)."""
    with session_scope() as s:
        app = s.get(TrackedApp, app_id)
        if app is not None:
            s.delete(app)


# -------------------------------------------------------------------- трекер
class UsageTracker:
    def __init__(self,
                 poll_seconds: float = config.TRACK_POLL_SECONDS,
                 idle_limit_seconds: float = config.DEFAULT_IDLE_MINUTES * 60,
                 flush_seconds: float = config.TRACK_FLUSH_SECONDS,
                 get_foreground: Callable[[], Optional[str]] = system_info.foreground_process_name,
                 get_idle: Callable[[], float] = system_info.idle_seconds):
        # Функции get_foreground и get_idle передаются снаружи - в тестах их
        # можно подменить на свои, не трогая настоящую Windows.
        self.poll_seconds = poll_seconds
        self.idle_limit_seconds = idle_limit_seconds
        self.flush_seconds = flush_seconds
        self._get_foreground = get_foreground
        self._get_idle = get_idle

        self._tracked: dict[str, int] = {}          # имя процесса -> id программы (только включённые)
        self._current: Optional[str] = None         # какой процесс считаем прямо сейчас
        self._current_app_id: Optional[int] = None  # запоминаем id, чтобы при выключении программы посреди отрезка ничего не пропало
        self._segment_start: Optional[datetime] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()              # "флажок", по которому поток понимает, что пора остановиться
        self._lock = threading.Lock()               # чтобы окно и поток не меняли данные одновременно

    # -- управление ------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self.reload_tracked_apps()
        self._stop.clear()
        # daemon=True: поток не мешает программе закрыться
        self._thread = threading.Thread(target=self._loop, name="usage-tracker", daemon=True)
        self._thread.start()
        log.info("Трекер приложений запущен")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.finish(datetime.now())
        log.info("Трекер приложений остановлен")

    def reload_tracked_apps(self) -> None:
        """Перечитать список программ (вызывается после изменений в окне)."""
        with session_scope() as s:
            rows = s.execute(
                select(TrackedApp.process_name, TrackedApp.id).where(TrackedApp.enabled.is_(True))
            ).all()
        with self._lock:
            self._tracked = {name: app_id for name, app_id in rows}

    # -- главная логика (покрыта тестами) ---------------------------------
    def tick(self, process_name: Optional[str], now: datetime, idle_trim_seconds: float = 0.0) -> None:
        """Одно наблюдение. process_name=None значит: впереди нет нужной программы или пользователь отошёл.

        idle_trim_seconds: если пользователь только что "ушёл", последние N секунд
        он уже ничего не делал - их отрезаем от закрываемого отрезка.
        """
        with self._lock:
            if process_name is not None and process_name not in self._tracked:
                process_name = None   # программа не из списка - как будто её нет

            if process_name != self._current:
                # программа сменилась: закрываем старый отрезок и начинаем новый
                if process_name is None:
                    segment_end = now - timedelta(seconds=idle_trim_seconds)
                else:
                    segment_end = now
                self._close_segment(segment_end)
                self._current = process_name
                self._current_app_id = self._tracked.get(process_name) if process_name else None
                self._segment_start = now if process_name else None
            elif process_name and self._segment_start is not None:
                # та же программа уже долго - сохраняем кусок и продолжаем считать
                if (now - self._segment_start).total_seconds() >= self.flush_seconds:
                    self._close_segment(now)
                    self._segment_start = now

    def finish(self, now: datetime) -> None:
        """Сохранить то, что сейчас считается (при остановке или выходе из программы)."""
        with self._lock:
            self._close_segment(now)
            self._current = None
            self._current_app_id = None
            self._segment_start = None

    # -- внутреннее ------------------------------------------------------
    def _close_segment(self, end: datetime) -> None:
        """Записывает текущий отрезок в базу (если он есть и длиннее секунды)."""
        if self._current is None or self._segment_start is None:
            return
        app_id = self._current_app_id
        seconds = int((end - self._segment_start).total_seconds())
        if app_id is None or seconds < 1:
            return
        try:
            with session_scope() as s:
                s.add(AppSession(app_id=app_id, start_time=self._segment_start,
                                 end_time=end, duration_seconds=seconds))
        except Exception:
            log.exception("Не удалось сохранить отрезок времени")

    def _loop(self) -> None:
        """То, что делает фоновый поток: ждёт poll_seconds и делает одно наблюдение."""
        # wait() возвращает True, когда выставили флажок остановки - тогда цикл заканчивается
        while not self._stop.wait(self.poll_seconds):
            try:
                idle = self._get_idle()
                if idle >= self.idle_limit_seconds:
                    self.tick(None, datetime.now(), idle_trim_seconds=idle)
                else:
                    self.tick(self._get_foreground(), datetime.now())
            except Exception:
                log.exception("Ошибка в цикле трекера")   # одна ошибка не должна останавливать слежение

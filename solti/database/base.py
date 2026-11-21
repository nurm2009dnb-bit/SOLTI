"""
Подключение к базе данных: движок, сессии и первый запуск.
SQLAlchemy - библиотека, которая позволяет работать с базой через классы
Python, а не писать SQL-запросы руками. Сама база - обычный файл SQLite.
"""
from __future__ import annotations
from contextlib import contextmanager   # позволяет написать свой блок "with ..."
from typing import Iterator
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from .. import config

class Base(DeclarativeBase):
    """Родительский класс для всех таблиц (см. models.py)."""
# Движок и "фабрика" сессий создаются один раз в init_db() и живут всё время работы программы
_engine: Engine | None = None
_make_session: sessionmaker[Session] | None = None

def _python_lower(value):
    """lower() для SQLite, который понимает и кириллицу (None оставляем как есть)."""
    return value.lower() if isinstance(value, str) else value

def init_db(url: str | None = None) -> None:
    """Подключается к базе и создаёт все таблицы. Можно вызывать несколько раз (так делают тесты)."""
    global _engine, _make_session
    # Импорт нужен только ради побочного эффекта: при импорте классы таблиц
    # регистрируются в Base, и create_all() узнаёт, какие таблицы создавать.
    from . import models

    if _engine is not None:
        _engine.dispose()   # закрываем старое подключение, если оно было

    _engine = create_engine(
        url or config.DATABASE_URL,
        # Базой пользуются два потока (окно и трекер), поэтому отключаем проверку
        # "только один поток" и ждём до 30 секунд, если база занята.
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(_engine, "connect")
    def _tune_sqlite(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")   # без этого SQLite не удаляет связанные записи (ON DELETE CASCADE)
        cursor.execute("PRAGMA journal_mode=WAL")  # режим, в котором окно и трекер могут писать одновременно
        cursor.close()
        # Встроенная функция lower() в SQLite понимает только латиницу, и поиск
        # "титан" не находил бы "Титан". Подменяем её на str.lower() из Python,
        # который знает русские буквы. На ней работает поиск без учёта регистра (ilike).
        connection.create_function("lower", 1, _python_lower, deterministic=True)

    _make_session = sessionmaker(bind=_engine, expire_on_commit=False)
    Base.metadata.create_all(_engine)

    from .seed import add_default_data
    add_default_data()

@contextmanager
def session_scope() -> Iterator[Session]:
    """
    Открывает сессию с базой на время блока with.
    Пример:  with session_scope() as s:  s.add(...)
    Если всё прошло хорошо - изменения сохраняются (commit), если была ошибка -
    откатываются (rollback). Сессия закрывается в любом случае.
    """
    if _make_session is None:
        raise RuntimeError("База данных не подключена. Сначала вызовите init_db().")
    session = _make_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

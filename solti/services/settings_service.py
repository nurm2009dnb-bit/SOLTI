"""Маленькое хранилище настроек пользователя (папка сортировки, тема, время простоя...).

Все значения хранятся строками в таблице settings.
"""
from __future__ import annotations

from ..database.base import session_scope
from ..database.models import Setting


def get_setting(key: str, default: str = "") -> str:
    """Возвращает значение настройки или default, если её ещё нет."""
    with session_scope() as s:
        row = s.get(Setting, key)
        return row.value if row is not None else default


def set_setting(key: str, value: str) -> None:
    """Сохраняет настройку: создаёт новую строку или обновляет старую."""
    with session_scope() as s:
        row = s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=value))
        else:
            row.value = value


# Флажки (да/нет) храним как "1" и "0"
def get_bool(key: str, default: bool = False) -> bool:
    return get_setting(key, "1" if default else "0") == "1"


def set_bool(key: str, value: bool) -> None:
    set_setting(key, "1" if value else "0")

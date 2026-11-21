"""Функции, зависящие от Windows: какая программа сейчас активна и не отошёл ли пользователь.

В Windows используется Win32 API через ctypes (встроен в Python, ничего ставить не нужно).
На других системах функции возвращают безопасные значения, чтобы остальная программа работала.
Читаются только ИМЕНА процессов - никаких заголовков окон и содержимого.
"""
from __future__ import annotations

import sys
from typing import Optional

import psutil   # библиотека для информации о процессах: по номеру процесса узнаём его имя

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes                    # вызов функций из системных DLL Windows прямо из Python
    from ctypes import wintypes      # типы Windows (HWND, DWORD...) для ctypes

    _user32 = ctypes.windll.user32       # окна, мышь, клавиатура
    _kernel32 = ctypes.windll.kernel32   # системное время

    # Явно описываем типы аргументов и результатов: без этого 64-битная Windows
    # может обрезать номер окна (HWND) и функции будут возвращать мусор.
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _kernel32.GetTickCount.restype = wintypes.DWORD

    class _LASTINPUTINFO(ctypes.Structure):
        """Структура Windows, в которую система записывает время последнего нажатия/движения мыши."""
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    # Тип функции обратного вызова для EnumWindows (Windows вызывает её для каждого окна)
    _EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _process_name(pid: int) -> Optional[str]:
    """Имя процесса по его номеру, например 'chrome.exe'."""
    try:
        return psutil.Process(pid).name().lower()
    except (psutil.Error, OSError):
        return None  # системный защищённый процесс или он уже закрылся


def foreground_process_name() -> Optional[str]:
    """Имя программы, в окне которой сейчас работает пользователь."""
    if not IS_WINDOWS:
        return None
    window = _user32.GetForegroundWindow()
    if not window:
        return None
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
    return _process_name(pid.value) if pid.value else None


def idle_seconds() -> float:
    """Сколько секунд прошло с последнего нажатия клавиши или движения мыши."""
    if not IS_WINDOWS:
        return 0.0
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    # & 0xFFFFFFFF - защита от "переполнения" счётчика, который сбрасывается раз в ~49 дней
    millis = (_kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return millis / 1000.0


def running_app_names() -> list[str]:
    """Программы, у которых сейчас есть видимое окно (то, что пользователь называет "открытые программы")."""
    names: set[str] = set()
    if IS_WINDOWS:
        pids: set[int] = set()

        def _remember_window(window, _lparam):
            # берём только видимые окна с заголовком - так отсекаются служебные невидимые окна
            if _user32.IsWindowVisible(window) and _user32.GetWindowTextLengthW(window) > 0:
                pid = wintypes.DWORD()
                _user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
                if pid.value:
                    pids.add(pid.value)
            return True   # True = продолжать перебор окон

        _user32.EnumWindows(_EnumWindowsProc(_remember_window), 0)
        for pid in pids:
            name = _process_name(pid)
            if name:
                names.add(name)
    else:
        # запасной вариант для Linux/macOS, чтобы окно выбора не было пустым при разработке
        for process in psutil.process_iter(["name"]):
            if process.info.get("name"):
                names.add(process.info["name"].lower())
    return sorted(names)

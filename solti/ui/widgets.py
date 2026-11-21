"""Мелкие помощники, общие для всех разделов: таблицы, окна сообщений, разбор чисел."""
from __future__ import annotations

from datetime import datetime
from tkinter import messagebox, ttk   # messagebox - стандартные окна "Ошибка"/"Да-Нет"; ttk - таблица Treeview
from typing import Iterable, Optional, Sequence

import customtkinter as ctk   # CustomTkinter - современный вид для Tkinter со светлой и тёмной темой

from .. import config

# Цвета, которыми подсвечивается текст состояния
OK_COLOR = "#2fa572"
WARN_COLOR = "#e0a030"
ERR_COLOR = "#d9534f"
MUTED_COLOR = "gray"

# Цвета кнопок (пара значений = светлая тема, тёмная тема)
BLUE = ("#3b8ed0", "#1f6aa5")
BLUE_HOVER = ("#36719f", "#144870")
RED, RED_HOVER = "#c0392b", "#a93226"
GREEN, GREEN_HOVER = "#2fa572", "#268c60"
GRAY, GRAY_HOVER = "gray40", "gray30"


# ------------------------------------------------------------- окна сообщений
# Разделы вызывают эти функции, а не messagebox напрямую: тогда тесты могут их подменить
# и не ждать, пока кто-то нажмёт "ОК".
def show_error(message: str) -> None:
    messagebox.showerror(config.APP_NAME, message)


def show_info(message: str) -> None:
    messagebox.showinfo(config.APP_NAME, message)


def ask_yes_no(message: str) -> bool:
    return bool(messagebox.askyesno(config.APP_NAME, message))


class TextDialog(ctk.CTkToplevel):
    """Небольшое окно "введите текст" с русскими кнопками.

    Встроенный CTkInputDialog подписывает кнопки по-английски (Ok / Cancel),
    поэтому сделали свой.
    """

    def __init__(self, title: str, prompt: str, initial: str = ""):
        super().__init__()
        self.title(title)
        self.geometry("380x170")
        self.resizable(False, False)
        self._result: Optional[str] = None

        ctk.CTkLabel(self, text=prompt, anchor="w", justify="left").pack(fill="x", padx=16, pady=(16, 6))
        self.entry = ctk.CTkEntry(self)
        self.entry.pack(fill="x", padx=16)
        self.entry.insert(0, initial)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=16, pady=16)
        ctk.CTkButton(buttons, text="ОК", width=110, command=self._ok).pack(side="left")
        ctk.CTkButton(buttons, text="Отмена", width=110, fg_color=GRAY, hover_color=GRAY_HOVER,
                      command=self.destroy).pack(side="right")
        self.entry.bind("<Return>", lambda _e: self._ok())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(100, self._focus)

    def _focus(self) -> None:
        try:
            self.grab_set()          # пока окно открыто, основное окно не реагирует на клики
            self.entry.focus_set()
        except Exception:
            pass

    def _ok(self) -> None:
        self._result = self.entry.get()
        self.destroy()

    def get_input(self) -> Optional[str]:
        """Ждёт, пока окно закроют, и возвращает текст (или None, если нажали "Отмена")."""
        self.wait_window()
        return self._result


def ask_text(title: str, prompt: str, initial: str = "") -> Optional[str]:
    return TextDialog(title, prompt, initial).get_input()


# -------------------------------------------------------------------- таблицы
def setup_ttk_style() -> None:
    """Подстраивает таблицы ttk.Treeview под текущую тему (светлую или тёмную).

    Treeview - это не виджет CustomTkinter, сам он тему не меняет, поэтому
    функцию нужно вызывать при запуске и при каждом переключении темы.
    """
    dark = ctk.get_appearance_mode() == "Dark"
    background = "#2b2b2b" if dark else "#ffffff"
    text = "#dce4ee" if dark else "#1a1a1a"
    header = "#3a3a3a" if dark else "#e3e3e3"

    style = ttk.Style()
    style.theme_use("default")   # у темы "default" можно менять цвета (у системной Windows - нет)
    style.configure("Treeview", background=background, foreground=text, fieldbackground=background,
                    borderwidth=0, rowheight=26, font=("Segoe UI", 10))
    style.map("Treeview", background=[("selected", "#1f6aa5")], foreground=[("selected", "#ffffff")])
    style.configure("Treeview.Heading", background=header, foreground=text, relief="flat",
                    font=("Segoe UI", 10, "bold"))
    style.map("Treeview.Heading", background=[("active", header)])


def make_table(parent, columns: Sequence[tuple], height: int = 8, selectmode: str = "browse"):
    """Создаёт таблицу с прокруткой.

    columns: [(id, заголовок, ширина[, выравнивание])].
    Возвращает (рамка, таблица); рамку размещает тот, кто вызвал.
    """
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    tree = ttk.Treeview(frame, columns=[column[0] for column in columns], show="headings",
                        height=height, selectmode=selectmode)
    for column in columns:
        column_id, heading, width = column[0], column[1], column[2]
        anchor = column[3] if len(column) > 3 else "w"
        tree.heading(column_id, text=heading, anchor=anchor)
        tree.column(column_id, width=width, anchor=anchor, stretch=True)
    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    return frame, tree


def fill_table(tree: ttk.Treeview, rows: Iterable[tuple[str, Sequence]], keep_selection: bool = True) -> None:
    """Заполняет таблицу заново. rows: [(id строки, значения)].

    Если строка была выделена и после обновления она всё ещё есть - выделение сохраняется.
    """
    previously_selected = set(tree.selection()) if keep_selection else set()
    tree.delete(*tree.get_children())
    for row_id, values in rows:
        tree.insert("", "end", iid=row_id, values=tuple(values))
    still_there = [row_id for row_id in previously_selected if tree.exists(row_id)]
    if still_there:
        tree.selection_set(still_there)


def selected_id(tree: ttk.Treeview) -> Optional[int]:
    """id выделенной строки как число (в таблицах id строки = id записи в базе)."""
    selection = tree.selection()
    if not selection:
        return None
    try:
        return int(selection[0])
    except ValueError:
        return None   # например, строки предпросмотра имеют id вида "p0", это не записи базы


# ---------------------------------------------------------------- ввод данных
def parse_int(text: str, label: str, default: Optional[int] = None, minimum: Optional[int] = None) -> Optional[int]:
    """Превращает текст из поля в целое число с понятной ошибкой. Пустое поле -> default."""
    text = text.strip()
    if not text:
        return default
    try:
        value = int(text)
    except ValueError:
        raise ValueError(f"Поле «{label}» должно быть целым числом.") from None
    if minimum is not None and value < minimum:
        raise ValueError(f"Поле «{label}» должно быть не меньше {minimum}.")
    return value


def fmt_dt(value: datetime) -> str:
    """Дата и время в привычном виде: 14.11.2026 12:35."""
    return value.strftime("%d.%m.%Y %H:%M")


def set_entry(entry: ctk.CTkEntry, text: str) -> None:
    """Заменяет текст в поле ввода."""
    entry.delete(0, "end")
    entry.insert(0, text)


def label_row(parent, text: str, **kwargs) -> ctk.CTkLabel:
    """Подпись, выровненная по левому краю."""
    return ctk.CTkLabel(parent, text=text, anchor="w", **kwargs)

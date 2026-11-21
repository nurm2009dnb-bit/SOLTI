"""Раздел "Пароли": зашифрованное хранилище с мастер-паролем, автоблокировкой и очисткой буфера обмена."""
from __future__ import annotations

import time
import tkinter as tk
from typing import Optional

import customtkinter as ctk

from .. import config
from ..services.vault_service import (
    MIN_MASTER_LENGTH, Vault, VaultLockedError, WrongPasswordError, generate_password,
)
from . import widgets as w

HIDDEN_CHAR = "•"   # чем закрываются символы пароля в поле ввода


class VaultTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.vault = Vault()
        self._selected: Optional[int] = None
        self._last_activity = time.monotonic()   # monotonic не "прыгает" при переводе часов

        # Два экрана: экран блокировки и основной. Показывается всегда только один.
        self.lock_frame = ctk.CTkFrame(self)
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._build_lock_frame()
        self._build_main_frame()
        self._show_lock()

        # Любое нажатие клавиши или клик в окне считается активностью (для автоблокировки)
        root = self.winfo_toplevel()
        root.bind("<Key>", self._touch, add="+")
        root.bind("<Button>", self._touch, add="+")
        self._job = self.after(20000, self._autolock_check)

    # ============================================================ экран блокировки
    def _build_lock_frame(self) -> None:
        box = ctk.CTkFrame(self.lock_frame, fg_color="transparent")
        box.place(relx=0.5, rely=0.42, anchor="center")   # по центру экрана
        self.lock_title = ctk.CTkLabel(box, text="", font=ctk.CTkFont(size=20, weight="bold"))
        self.lock_title.pack(pady=(0, 6))
        self.lock_hint = ctk.CTkLabel(box, text="", text_color=w.MUTED_COLOR, justify="center")
        self.lock_hint.pack(pady=(0, 12))
        self.master_entry = ctk.CTkEntry(box, show=HIDDEN_CHAR, width=300, placeholder_text="Мастер-пароль")
        self.master_entry.pack(pady=4)
        self.confirm_entry = ctk.CTkEntry(box, show=HIDDEN_CHAR, width=300,
                                          placeholder_text="Повторите мастер-пароль")
        self.unlock_btn = ctk.CTkButton(box, text="", width=300, command=self._unlock_or_create)
        self.unlock_btn.pack(pady=10)
        self.lock_error = ctk.CTkLabel(box, text="", text_color=w.ERR_COLOR)
        self.lock_error.pack()
        for entry in (self.master_entry, self.confirm_entry):
            entry.bind("<Return>", lambda _e: self._unlock_or_create())   # Enter = нажать кнопку

    def _show_lock(self) -> None:
        self.main_frame.pack_forget()
        self.lock_frame.pack(fill="both", expand=True, padx=6, pady=8)
        self.master_entry.delete(0, "end")
        self.confirm_entry.delete(0, "end")
        self.lock_error.configure(text="")
        if Vault.is_initialized():
            self.lock_title.configure(text="Хранилище закрыто")
            self.lock_hint.configure(text="Введите мастер-пароль, чтобы открыть его.")
            self.confirm_entry.pack_forget()
            self.unlock_btn.configure(text="Открыть")
        else:
            # Первый запуск: просим придумать пароль и повторить его
            self.lock_title.configure(text="Создание хранилища")
            self.lock_hint.configure(text=(f"Придумайте мастер-пароль (не короче {MIN_MASTER_LENGTH} символов).\n"
                                           "Восстановить его нельзя - если забудете, пароли пропадут."))
            self.confirm_entry.pack(pady=4, after=self.master_entry)
            self.unlock_btn.configure(text="Создать хранилище")

    def _unlock_or_create(self) -> None:
        master = self.master_entry.get()
        try:
            if Vault.is_initialized():
                self.vault.unlock(master)
            else:
                if master != self.confirm_entry.get():
                    raise ValueError("Пароли не совпадают.")
                self.vault.setup(master)
        except (ValueError, WrongPasswordError) as exc:
            self.lock_error.configure(text=str(exc))
            return
        self._touch()
        self._show_main()

    # ============================================================ основной экран
    def _build_main_frame(self) -> None:
        bar = ctk.CTkFrame(self.main_frame)
        bar.pack(fill="x", pady=(8, 4))
        self.search_entry = ctk.CTkEntry(bar, placeholder_text="Поиск по сайту, логину или заметкам...", width=340)
        self.search_entry.pack(side="left", padx=8, pady=8)
        self.search_entry.bind("<KeyRelease>", lambda _e: self.refresh())
        ctk.CTkButton(bar, text="Закрыть хранилище", width=150, fg_color=w.GRAY, hover_color=w.GRAY_HOVER,
                      command=self.lock).pack(side="right", padx=8)

        frame, self.tree = w.make_table(self.main_frame, [
            ("site", "Сайт / сервис", 260), ("user", "Логин", 240), ("updated", "Изменено", 150)], height=9)
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        form = ctk.CTkFrame(self.main_frame)
        form.pack(fill="x", pady=8)
        form.columnconfigure((1, 3), weight=1)
        self.f_site = ctk.CTkEntry(form, placeholder_text="github.com")
        self.f_user = ctk.CTkEntry(form, placeholder_text="логин или e-mail")
        self.f_pass = ctk.CTkEntry(form, show=HIDDEN_CHAR, placeholder_text="пароль")
        self.f_notes = ctk.CTkEntry(form, placeholder_text="заметки (необязательно)")
        self.show_var = tk.BooleanVar(value=False)

        w.label_row(form, "Сайт").grid(row=0, column=0, padx=8, pady=4, sticky="w")
        self.f_site.grid(row=0, column=1, padx=8, pady=4, sticky="ew")
        w.label_row(form, "Логин").grid(row=0, column=2, padx=8, pady=4, sticky="w")
        self.f_user.grid(row=0, column=3, padx=8, pady=4, sticky="ew")
        w.label_row(form, "Пароль").grid(row=1, column=0, padx=8, pady=4, sticky="w")
        self.f_pass.grid(row=1, column=1, padx=8, pady=4, sticky="ew")
        options = ctk.CTkFrame(form, fg_color="transparent")
        options.grid(row=1, column=2, columnspan=2, padx=8, pady=4, sticky="w")
        ctk.CTkCheckBox(options, text="Показать", variable=self.show_var, width=80,
                        command=self._toggle_show).pack(side="left")
        ctk.CTkButton(options, text="Сгенерировать", width=120, command=self._generate).pack(side="left", padx=8)
        w.label_row(form, "Заметки").grid(row=2, column=0, padx=8, pady=4, sticky="w")
        self.f_notes.grid(row=2, column=1, columnspan=3, padx=8, pady=4, sticky="ew")

        buttons = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        buttons.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(buttons, text="Добавить", width=100, command=self._add).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Сохранить изменения", width=160, command=self._update).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Копировать пароль", width=150, fg_color=w.GREEN, hover_color=w.GREEN_HOVER,
                      command=self._copy).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Удалить", width=90, fg_color=w.RED, hover_color=w.RED_HOVER,
                      command=self._delete).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Очистить форму", width=130, fg_color=w.GRAY, hover_color=w.GRAY_HOVER,
                      command=self._clear).pack(side="left", padx=4)
        self.msg = ctk.CTkLabel(self.main_frame, text="", text_color=w.MUTED_COLOR, anchor="w")
        self.msg.pack(fill="x", padx=6)

    def _show_main(self) -> None:
        self.lock_frame.pack_forget()
        self.main_frame.pack(fill="both", expand=True, padx=6)
        self.msg.configure(text=f"Хранилище закроется само после {config.VAULT_AUTOLOCK_MINUTES} минут бездействия.")
        self.refresh()

    def lock(self) -> None:
        """Закрыть хранилище: стираем ключ из памяти и всё, что видно на экране."""
        self.vault.lock()
        self._clear()
        w.fill_table(self.tree, [], keep_selection=False)
        self.search_entry.delete(0, "end")
        self._show_lock()

    # ---------------------------------------------------------------- помощники
    def _touch(self, _event=None) -> None:
        """Отмечает, что пользователь что-то сделал (сбрасывает отсчёт автоблокировки)."""
        self._last_activity = time.monotonic()

    def _autolock_check(self) -> None:
        """Каждые 20 секунд проверяем, не пора ли закрыть хранилище."""
        idle = time.monotonic() - self._last_activity
        if self.vault.is_unlocked and idle > config.VAULT_AUTOLOCK_MINUTES * 60:
            self.lock()
        self._job = self.after(20000, self._autolock_check)

    def _toggle_show(self) -> None:
        if self.show_var.get():
            # пароль расшифровывается только в тот момент, когда его попросили показать
            if self._selected is not None and not self.f_pass.get():
                try:
                    w.set_entry(self.f_pass, self.vault.reveal(self._selected))
                except (ValueError, VaultLockedError) as exc:
                    w.show_error(str(exc))
            self.f_pass.configure(show="")
        else:
            self.f_pass.configure(show=HIDDEN_CHAR)

    def _generate(self) -> None:
        w.set_entry(self.f_pass, generate_password(16))
        self.show_var.set(True)
        self.f_pass.configure(show="")   # сгенерированный пароль сразу показываем, чтобы его было видно

    def _clear(self) -> None:
        self._selected = None
        if self.tree.selection():
            self.tree.selection_remove(*self.tree.selection())
        for entry in (self.f_site, self.f_user, self.f_pass, self.f_notes):
            entry.delete(0, "end")
        self.show_var.set(False)
        self.f_pass.configure(show=HIDDEN_CHAR)

    def refresh(self) -> None:
        if not self.vault.is_unlocked:
            return
        rows = [(str(c.id), (c.site, c.username, w.fmt_dt(c.updated_at)))
                for c in self.vault.search(self.search_entry.get())]
        w.fill_table(self.tree, rows)

    def _on_select(self, _event=None) -> None:
        cred_id = w.selected_id(self.tree)
        if cred_id is None:
            return
        row = next((c for c in self.vault.search() if c.id == cred_id), None)
        if row is None:
            return
        self._selected = cred_id
        w.set_entry(self.f_site, row.site)
        w.set_entry(self.f_user, row.username)
        w.set_entry(self.f_notes, row.notes)
        self.f_pass.delete(0, "end")            # пароль НЕ показываем, пока о нём не попросят
        self.show_var.set(False)
        self.f_pass.configure(show=HIDDEN_CHAR)

    # ---------------------------------------------------------------- действия
    def _guard(self, action) -> bool:
        """Выполняет действие и аккуратно обрабатывает ошибки (закрытое хранилище, неверные данные)."""
        self._touch()
        try:
            action()
            return True
        except VaultLockedError:
            self.lock()
        except ValueError as exc:
            w.show_error(str(exc))
        return False

    def _add(self) -> None:
        def add_entry():
            self.vault.add(self.f_site.get(), self.f_user.get(), self.f_pass.get(), self.f_notes.get())
            self._clear()
            self.refresh()
        self._guard(add_entry)

    def _update(self) -> None:
        if self._selected is None:
            w.show_error("Сначала выберите запись в таблице.")
            return

        def save_changes():
            # пустое поле пароля = оставить старый пароль
            password = self.f_pass.get() or self.vault.reveal(self._selected)
            self.vault.update(self._selected, self.f_site.get(), self.f_user.get(), password, self.f_notes.get())
            self.refresh()
            self.msg.configure(text="Запись сохранена.")
        self._guard(save_changes)

    def _delete(self) -> None:
        if self._selected is None:
            w.show_error("Сначала выберите запись в таблице.")
            return
        if w.ask_yes_no("Удалить эту запись навсегда?"):
            def delete_entry():
                self.vault.delete(self._selected)
                self._clear()
                self.refresh()
            self._guard(delete_entry)

    def _copy(self) -> None:
        if self._selected is None:
            w.show_error("Сначала выберите запись в таблице.")
            return

        def copy_password():
            password = self.vault.reveal(self._selected)
            self.clipboard_clear()
            self.clipboard_append(password)
            self.msg.configure(text=f"Скопировано. Буфер обмена очистится через {config.CLIPBOARD_CLEAR_SECONDS} с.")
            self.after(config.CLIPBOARD_CLEAR_SECONDS * 1000, lambda: self._clear_clipboard(password))
        self._guard(copy_password)

    def _clear_clipboard(self, password: str) -> None:
        try:
            # стираем только если в буфере всё ещё наш пароль - чужое не трогаем
            if self.clipboard_get() == password:
                self.clipboard_clear()
                self.msg.configure(text="Буфер обмена очищен.")
        except tk.TclError:
            pass   # буфер пуст или занят другой программой

    def shutdown(self) -> None:
        self.after_cancel(self._job)
        self.vault.lock()

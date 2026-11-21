"""Раздел "Сортировка файлов": ручная сортировка, слежение за папкой, правила, отмена."""
from __future__ import annotations

import queue        # потокобезопасная очередь: фоновые потоки кладут события, окно их забирает
import threading
import tkinter as tk
from pathlib import Path
from typing import Optional

import customtkinter as ctk

from .. import config
from ..services import settings_service as settings
from ..services import sorter
from ..services.watcher import FolderWatcher
from . import widgets as w


class SorterTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.watcher: Optional[FolderWatcher] = None
        # Tkinter нельзя трогать из других потоков. Поэтому потоки только кладут
        # события в эту очередь, а окно раз в 0.4 с забирает их и обновляет экран.
        self._events: queue.Queue = queue.Queue()
        self._history_mode = True          # True - в таблице журнал, False - предпросмотр
        self._rule_id: Optional[int] = None

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True)
        self._build_sort_page(tabs.add("Сортировка"))
        self._build_rules_page(tabs.add("Правила"))

        self._load_history()
        self._load_rules()
        self._job = self.after(300, self._drain_events)
        if settings.get_bool("autowatch"):
            self._start_watching(silent=True)

    # ============================================================ страница сортировки
    def _build_sort_page(self, tab) -> None:
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", pady=(6, 4))
        w.label_row(top, "Папка для сортировки:").pack(side="left", padx=(4, 8))
        saved_folder = settings.get_setting("watch_folder", str(config.DEFAULT_WATCH_FOLDER))
        self.folder_var = tk.StringVar(value=saved_folder)
        self.folder_entry = ctk.CTkEntry(top, textvariable=self.folder_var)
        self.folder_entry.pack(side="left", fill="x", expand=True)
        self.browse_btn = ctk.CTkButton(top, text="Обзор...", width=90, command=self._browse)
        self.browse_btn.pack(side="left", padx=8)

        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", pady=4)
        ctk.CTkButton(bar, text="Предпросмотр", width=120, command=self._preview).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Сортировать", width=120, command=self._sort_now).pack(side="left", padx=4)
        self.watch_btn = ctk.CTkButton(bar, text="Начать слежение", width=150, command=self._toggle_watching)
        self.watch_btn.pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Отменить выбранное", width=150, fg_color=w.GRAY, hover_color=w.GRAY_HOVER,
                      command=self._undo_selected).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="Отменить последнее", width=150, fg_color=w.GRAY, hover_color=w.GRAY_HOVER,
                      command=self._undo_last).pack(side="right", padx=4)

        options = ctk.CTkFrame(tab, fg_color="transparent")
        options.pack(fill="x")
        self.autowatch_var = tk.BooleanVar(value=settings.get_bool("autowatch"))
        ctk.CTkCheckBox(options, text="Начинать слежение сразу при запуске программы",
                        variable=self.autowatch_var,
                        command=lambda: settings.set_bool("autowatch", self.autowatch_var.get())
                        ).pack(side="left", padx=6, pady=4)

        self.status = ctk.CTkLabel(tab, text="Слежение выключено.", text_color=w.MUTED_COLOR, anchor="w")
        self.status.pack(fill="x", padx=6, pady=(2, 0))
        self.table_title = ctk.CTkLabel(tab, text="Последние перемещения",
                                        font=ctk.CTkFont(weight="bold"), anchor="w")
        self.table_title.pack(fill="x", padx=6, pady=(6, 2))

        frame, self.tree = w.make_table(tab, [
            ("when", "Когда", 130), ("file", "Файл", 260), ("folder", "Куда", 190),
            ("why", "Почему", 190), ("state", "Состояние", 90)], height=10)
        frame.pack(fill="both", expand=True, pady=(0, 4))

    def _folder(self) -> Optional[Path]:
        """Папка из поля ввода; если её нет - показываем ошибку и возвращаем None."""
        folder = Path(self.folder_var.get().strip()).expanduser()
        if not folder.is_dir():
            w.show_error(f"Такой папки нет:\n{folder}")
            return None
        settings.set_setting("watch_folder", str(folder))
        return folder

    def _browse(self) -> None:
        from tkinter import filedialog   # стандартное окно выбора папки Windows
        chosen = filedialog.askdirectory(initialdir=self.folder_var.get() or str(Path.home()))
        if chosen:
            self.folder_var.set(chosen)

    def _set_status(self, text: str, color: str = w.MUTED_COLOR) -> None:
        self.status.configure(text=text, text_color=color)

    # ---- журнал и предпросмотр --------------------------------------------
    def _load_history(self) -> None:
        self._history_mode = True
        self.table_title.configure(text="Последние перемещения")
        base_folder = Path(self.folder_var.get()).expanduser()
        rows = []
        for entry in sorter.recent_log(100):
            parent = Path(entry.new_path).parent
            try:
                shown_folder = parent.relative_to(base_folder).as_posix()
            except ValueError:
                shown_folder = parent.name   # файл из другой папки - покажем только имя папки
            state = "отменено" if entry.undone else "перемещён"
            rows.append((str(entry.id), (w.fmt_dt(entry.timestamp), entry.file_name, shown_folder,
                                         entry.reason, state)))
        w.fill_table(self.tree, rows, keep_selection=False)

    def _preview(self) -> None:
        folder = self._folder()
        if folder is None:
            return
        plan = sorter.preview(folder)
        self._history_mode = False
        self.table_title.configure(text=f"Предпросмотр: будет перемещено файлов - {len(plan)} "
                                        f"(пока ничего не тронуто)")
        rows = [(f"p{number}", ("", path.name, decision.folder, decision.reason, "предпросмотр"))
                for number, (path, decision) in enumerate(plan)]
        w.fill_table(self.tree, rows, keep_selection=False)
        if plan:
            self._set_status("Предпросмотр готов. Нажмите «Сортировать», чтобы переместить файлы.")
        else:
            self._set_status("В этой папке нечего сортировать.")

    # ---- сортировка ---------------------------------------------------------
    def _sort_now(self) -> None:
        folder = self._folder()
        if folder is None:
            return
        count = len(sorter.preview(folder))
        if count == 0:
            self._set_status("В этой папке нечего сортировать.")
            return
        if not w.ask_yes_no(f"Разложить файлы ({count} шт.) по подпапкам в\n{folder}?\n\n"
                            f"Потом это можно отменить."):
            return
        self._set_status("Сортирую...", w.WARN_COLOR)

        # Перемещение может занять время, поэтому делаем его в фоне, чтобы окно не зависло
        def work() -> None:
            try:
                moved = sorter.sort_folder(folder)
                self._events.put(("batch", len(moved)))
            except Exception as exc:
                self._events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    # ---- слежение -----------------------------------------------------------
    def _toggle_watching(self) -> None:
        if self.watcher and self.watcher.is_running:
            self._stop_watching()
        else:
            self._start_watching()

    def _start_watching(self, silent: bool = False) -> None:
        # silent=True - запуск при старте программы: без окон с ошибками
        folder = Path(self.folder_var.get()).expanduser() if silent else self._folder()
        if folder is None or not folder.is_dir():
            return
        self.watcher = FolderWatcher(folder,
                                     on_result=lambda result: self._events.put(("moved", result)),
                                     on_error=lambda message: self._events.put(("error", message)))
        try:
            self.watcher.start()
        except Exception as exc:
            self.watcher = None
            w.show_error(f"Не удалось начать слежение: {exc}")
            return
        self.watch_btn.configure(text="Остановить слежение", fg_color=w.RED, hover_color=w.RED_HOVER)
        # пока идёт слежение, менять папку нельзя
        self.folder_entry.configure(state="disabled")
        self.browse_btn.configure(state="disabled")
        self._set_status(f"Слежу за {folder} - новые файлы сортируются сами.", w.OK_COLOR)

    def _stop_watching(self) -> None:
        if self.watcher:
            self.watcher.stop()
        self.watcher = None
        self.watch_btn.configure(text="Начать слежение", fg_color=w.BLUE, hover_color=w.BLUE_HOVER)
        self.folder_entry.configure(state="normal")
        self.browse_btn.configure(state="normal")
        self._set_status("Слежение выключено.")

    # ---- отмена -------------------------------------------------------------
    def _undo_selected(self) -> None:
        log_id = w.selected_id(self.tree) if self._history_mode else None
        if log_id is None:
            w.show_error("Сначала выберите строку в «Последних перемещениях».")
            return
        self._run_undo(lambda: sorter.undo(log_id))

    def _undo_last(self) -> None:
        self._run_undo(sorter.undo_last)

    def _run_undo(self, action) -> None:
        try:
            restored = action()
        except (ValueError, OSError) as exc:
            w.show_error(str(exc))
            return
        self._load_history()
        self._set_status(f"Возвращено: {restored}", w.OK_COLOR)

    # ---- события из фоновых потоков ------------------------------------------
    def _drain_events(self) -> None:
        """Забирает все накопившиеся события из очереди и показывает их. Повторяется каждые 0.4 с."""
        need_refresh = False
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "moved":
                    self._set_status(f"Отсортирован {payload.destination.name}  ->  {payload.folder}", w.OK_COLOR)
                    need_refresh = True
                elif kind == "batch":
                    self._set_status(f"Готово: перемещено файлов - {payload}.", w.OK_COLOR)
                    need_refresh = True
                elif kind == "error":
                    self._set_status(f"Проблема: {payload}", w.ERR_COLOR)
        except queue.Empty:
            pass   # очередь опустела - это нормально
        if need_refresh:
            self._load_history()
        self._job = self.after(400, self._drain_events)

    # ============================================================ страница правил
    def _build_rules_page(self, tab) -> None:
        ctk.CTkLabel(tab, anchor="w", justify="left", wraplength=880, text=(
            "Файл перемещается по ПЕРВОМУ подходящему правилу (сначала с большим приоритетом). Правило "
            "подходит, когда в имени файла есть одно из ключевых слов И расширение есть в списке (одно из "
            "полей можно оставить пустым). Если ни одно правило не подошло, используется встроенная "
            "таблица расширений (Изображения, Видео, Документы...). Если в папке уже есть файл с таким же "
            "именем, к имени нового файла добавляется дата перемещения."
        )).pack(fill="x", padx=6, pady=(6, 4))

        frame, self.rules_tree = w.make_table(tab, [
            ("name", "Название", 150), ("keywords", "Ключевые слова", 230), ("ext", "Расширения", 120),
            ("folder", "Папка", 180), ("prio", "Приоритет", 80, "center"), ("on", "Вкл.", 50, "center")],
            height=7)
        frame.pack(fill="both", expand=True)
        self.rules_tree.bind("<<TreeviewSelect>>", self._rule_selected)

        form = ctk.CTkFrame(tab)
        form.pack(fill="x", pady=8)
        form.columnconfigure((1, 3), weight=1)
        self.r_name = ctk.CTkEntry(form, placeholder_text="Домашние задания")
        self.r_keywords = ctk.CTkEntry(form, placeholder_text="домашка, дз, homework")
        self.r_ext = ctk.CTkEntry(form, placeholder_text=".pdf, .docx  (необязательно)")
        self.r_folder = ctk.CTkEntry(form, placeholder_text="Учёба/Домашние задания")
        self.r_prio = ctk.CTkEntry(form, width=80, placeholder_text="0")
        self.r_enabled = tk.BooleanVar(value=True)

        w.label_row(form, "Название").grid(row=0, column=0, padx=8, pady=4, sticky="w")
        self.r_name.grid(row=0, column=1, padx=8, pady=4, sticky="ew")
        w.label_row(form, "Ключевые слова").grid(row=0, column=2, padx=8, pady=4, sticky="w")
        self.r_keywords.grid(row=0, column=3, padx=8, pady=4, sticky="ew")
        w.label_row(form, "Расширения").grid(row=1, column=0, padx=8, pady=4, sticky="w")
        self.r_ext.grid(row=1, column=1, padx=8, pady=4, sticky="ew")
        w.label_row(form, "Папка").grid(row=1, column=2, padx=8, pady=4, sticky="w")
        self.r_folder.grid(row=1, column=3, padx=8, pady=4, sticky="ew")
        w.label_row(form, "Приоритет").grid(row=2, column=0, padx=8, pady=4, sticky="w")
        self.r_prio.grid(row=2, column=1, padx=8, pady=4, sticky="w")
        ctk.CTkCheckBox(form, text="Включено", variable=self.r_enabled).grid(row=2, column=3, padx=8, pady=4,
                                                                              sticky="w")

        buttons = ctk.CTkFrame(tab, fg_color="transparent")
        buttons.pack(fill="x")
        ctk.CTkButton(buttons, text="Добавить", width=110, command=self._rule_add).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Сохранить изменения", width=160,
                      command=self._rule_update).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Удалить", width=90, fg_color=w.RED, hover_color=w.RED_HOVER,
                      command=self._rule_delete).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Очистить форму", width=130, fg_color=w.GRAY, hover_color=w.GRAY_HOVER,
                      command=self._rule_clear).pack(side="left", padx=4)

    def _load_rules(self) -> None:
        rows = [(str(rule.id), (rule.name, rule.keywords, rule.extensions, rule.target_folder, rule.priority,
                                "да" if rule.enabled else "нет"))
                for rule in sorter.list_rules()]
        w.fill_table(self.rules_tree, rows)

    def _rule_values(self):
        """Значения из формы в том порядке, в котором их ждут add_rule / update_rule."""
        priority = w.parse_int(self.r_prio.get(), "Приоритет", default=0)
        return (self.r_name.get(), self.r_keywords.get(), self.r_ext.get(), self.r_folder.get(),
                priority, self.r_enabled.get())

    def _rule_selected(self, _event=None) -> None:
        """Клик по правилу в таблице - переносим его в форму для редактирования."""
        rule_id = w.selected_id(self.rules_tree)
        if rule_id is None:
            return
        rule = next((r for r in sorter.list_rules() if r.id == rule_id), None)
        if rule is None:
            return
        self._rule_id = rule_id
        w.set_entry(self.r_name, rule.name)
        w.set_entry(self.r_keywords, rule.keywords)
        w.set_entry(self.r_ext, rule.extensions)
        w.set_entry(self.r_folder, rule.target_folder)
        w.set_entry(self.r_prio, str(rule.priority))
        self.r_enabled.set(rule.enabled)

    def _rule_clear(self) -> None:
        self._rule_id = None
        self.rules_tree.selection_remove(*self.rules_tree.selection())
        for entry in (self.r_name, self.r_keywords, self.r_ext, self.r_folder, self.r_prio):
            entry.delete(0, "end")
        self.r_enabled.set(True)

    def _rule_add(self) -> None:
        try:
            sorter.add_rule(*self._rule_values())
        except ValueError as exc:
            w.show_error(str(exc))
            return
        self._rule_clear()
        self._load_rules()

    def _rule_update(self) -> None:
        if self._rule_id is None or w.selected_id(self.rules_tree) is None:
            w.show_error("Сначала выберите правило в таблице.")
            return
        try:
            sorter.update_rule(self._rule_id, *self._rule_values())
        except ValueError as exc:
            w.show_error(str(exc))
            return
        self._load_rules()

    def _rule_delete(self) -> None:
        rule_id = w.selected_id(self.rules_tree)
        if rule_id is None:
            w.show_error("Сначала выберите правило в таблице.")
            return
        if w.ask_yes_no("Удалить это правило?"):
            sorter.delete_rule(rule_id)
            self._rule_clear()
            self._load_rules()

    # ============================================================ закрытие
    def shutdown(self) -> None:
        """Вызывается при закрытии окна: останавливаем таймер обновления и слежение."""
        self.after_cancel(self._job)
        if self.watcher:
            self.watcher.stop()
            self.watcher = None

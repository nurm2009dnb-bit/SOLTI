"""Раздел "Трекер приложений": выбор программ, включение слежения, графики и статистика."""
from __future__ import annotations

import math
import tkinter as tk

import customtkinter as ctk
# matplotlib - библиотека графиков; FigureCanvasTkAgg встраивает график прямо в окно Tkinter
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .. import config
from ..services import settings_service as settings
from ..services import stats_service as stats
from ..services import system_info, usage_tracker
from ..services.usage_tracker import UsageTracker
from . import widgets as w

RANGES = {"Сегодня": 1, "7 дней": 7, "30 дней": 30}


class RunningAppsDialog(ctk.CTkToplevel):
    """Окно выбора одной или нескольких программ, которые открыты прямо сейчас."""

    def __init__(self, master, already: set[str], on_add):
        super().__init__(master)
        self.title("Добавить открытые программы")
        self.geometry("380x480")
        self.transient(master.winfo_toplevel())   # окно всегда поверх главного
        self._on_add = on_add

        ctk.CTkLabel(self, text="Сначала откройте нужную программу, потом выберите её здесь.\n"
                                "(Ctrl+клик - выбрать несколько.)",
                     justify="left").pack(padx=12, pady=(12, 6), anchor="w")
        frame, self.tree = w.make_table(self, [("name", "Программа (имя процесса)", 330)], height=14,
                                        selectmode="extended")
        frame.pack(fill="both", expand=True, padx=12)
        for name in system_info.running_app_names():
            if name not in already:   # уже добавленные не показываем
                self.tree.insert("", "end", iid=name, values=(name,))
        self.tree.bind("<Double-1>", lambda _e: self._add())

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=12)
        ctk.CTkButton(row, text="Добавить выбранные", command=self._add).pack(side="left")
        ctk.CTkButton(row, text="Отмена", fg_color=w.GRAY, hover_color=w.GRAY_HOVER,
                      command=self.destroy).pack(side="right")
        self.after(150, self._grab)

    def _grab(self) -> None:
        """Делает окно модальным (главное окно не реагирует, пока это открыто)."""
        try:
            self.grab_set()
        except tk.TclError:
            pass   # окно могли закрыть раньше, чем сработал after

    def _add(self) -> None:
        names = list(self.tree.selection())
        if names:
            self._on_add(names)
        self.destroy()


def _unit(max_seconds: int) -> tuple[float, str]:
    """В чём подписывать ось графика: в часах, если много, иначе в минутах."""
    if max_seconds >= 3 * 3600:
        return 3600.0, "часы"
    return 60.0, "минуты"


class UsageTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        idle_minutes = int(settings.get_setting("idle_minutes", str(config.DEFAULT_IDLE_MINUTES)) or 3)
        self.tracker = UsageTracker(idle_limit_seconds=idle_minutes * 60)
        self.days = 7

        self._build_top_bar(idle_minutes)
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=(6, 0))
        self._build_apps_panel(body)
        self._build_charts_panel(body)

        self._load_apps()
        self.refresh()
        if settings.get_bool("autostart_tracking") and usage_tracker.list_tracked_apps():
            self.track_switch.select()
            self._toggle_tracking()
        self._job = self.after(15000, self._auto_refresh)

    # --------------------------------------------------------------- разметка
    def _build_top_bar(self, idle_minutes: int) -> None:
        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=6, pady=(8, 0))
        self.track_switch = ctk.CTkSwitch(bar, text="Отслеживать программы", command=self._toggle_tracking,
                                          font=ctk.CTkFont(weight="bold"))
        self.track_switch.pack(side="left", padx=12, pady=10)
        self.track_status = ctk.CTkLabel(bar, text="Остановлено", text_color=w.MUTED_COLOR)
        self.track_status.pack(side="left", padx=6)

        self.autostart_var = tk.BooleanVar(value=settings.get_bool("autostart_tracking"))
        ctk.CTkCheckBox(bar, text="Включать при запуске", variable=self.autostart_var,
                        command=lambda: settings.set_bool("autostart_tracking", self.autostart_var.get())
                        ).pack(side="right", padx=12)
        ctk.CTkButton(bar, text="ОК", width=50, command=self._set_idle).pack(side="right")
        self.idle_entry = ctk.CTkEntry(bar, width=50, justify="center")
        self.idle_entry.insert(0, str(idle_minutes))
        self.idle_entry.pack(side="right", padx=6)
        w.label_row(bar, "Простой через (мин):").pack(side="right", padx=(12, 0))

        if not system_info.IS_WINDOWS:
            ctk.CTkLabel(self, text="Слежение за активным окном работает только в Windows; "
                                    "в этой системе ничего записываться не будет.",
                         text_color=w.WARN_COLOR).pack(anchor="w", padx=10)

    def _build_apps_panel(self, body) -> None:
        panel = ctk.CTkFrame(body)
        panel.pack(side="left", fill="y", padx=(6, 8), pady=4)
        ctk.CTkLabel(panel, text="Отслеживаемые программы",
                     font=ctk.CTkFont(weight="bold")).pack(padx=10, pady=(10, 4))
        ctk.CTkLabel(panel, text="Записываются только программы\nиз этого списка (и включённые).",
                     text_color=w.MUTED_COLOR, justify="left").pack(padx=10)
        frame, self.apps_tree = w.make_table(panel, [
            ("on", "Вкл.", 50, "center"), ("name", "Программа", 140), ("proc", "Процесс", 120)], height=12)
        frame.pack(fill="both", expand=True, padx=10, pady=8)
        self.apps_tree.bind("<Double-1>", lambda _e: self._toggle_app())

        buttons = [
            ("Добавить открытую...", self._add_running, None),
            ("Добавить по имени...", self._add_by_name, None),
            ("Включить / выключить", self._toggle_app, None),
            ("Переименовать...", self._rename_app, None),
            ("Удалить", self._remove_app, w.RED),
        ]
        for text, command, color in buttons:
            extra = {"fg_color": color, "hover_color": w.RED_HOVER} if color else {}
            ctk.CTkButton(panel, text=text, width=210, command=command, **extra).pack(padx=10, pady=3)
        ctk.CTkLabel(panel, text="").pack(pady=2)   # небольшой отступ снизу

    def _build_charts_panel(self, body) -> None:
        panel = ctk.CTkFrame(body, fg_color="transparent")
        panel.pack(side="left", fill="both", expand=True, pady=4)

        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x")
        self.range_buttons = ctk.CTkSegmentedButton(head, values=list(RANGES), command=self._range_changed)
        self.range_buttons.set("7 дней")
        self.range_buttons.pack(side="left")
        ctk.CTkButton(head, text="Обновить", width=90, command=self.refresh).pack(side="right")

        self.summary_label = ctk.CTkLabel(panel, text="", anchor="w", justify="left")
        self.summary_label.pack(fill="x", pady=6)

        # layout="constrained" - matplotlib сам подбирает отступы, чтобы подписи не обрезались
        self.figure = Figure(figsize=(7, 4), dpi=100, layout="constrained")
        self.canvas = FigureCanvasTkAgg(self.figure, master=panel)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    # ---------------------------------------------------------------- слежение
    def _toggle_tracking(self) -> None:
        if self.track_switch.get():
            if not any(app.enabled for app in usage_tracker.list_tracked_apps()):
                self.track_switch.deselect()
                w.show_error("Сначала добавьте в список хотя бы одну программу (и оставьте её включённой).")
                return
            self.tracker.start()
            self.track_status.configure(text="Запись идёт...", text_color=w.OK_COLOR)
        else:
            self.tracker.stop()
            self.track_status.configure(text="Остановлено", text_color=w.MUTED_COLOR)
            self.refresh()

    def _set_idle(self) -> None:
        try:
            minutes = w.parse_int(self.idle_entry.get(), "Простой", minimum=1)
            if minutes is None:
                raise ValueError("Введите время простоя в минутах.")
        except ValueError as exc:
            w.show_error(str(exc))
            return
        settings.set_setting("idle_minutes", str(minutes))
        self.tracker.idle_limit_seconds = minutes * 60
        self.track_status.configure(text=f"Простой теперь {minutes} мин", text_color=w.OK_COLOR)

    # ---------------------------------------------------- список программ
    def _load_apps(self) -> None:
        rows = [(str(app.id), ("вкл" if app.enabled else "выкл", app.display_name, app.process_name))
                for app in usage_tracker.list_tracked_apps()]
        w.fill_table(self.apps_tree, rows)
        self.tracker.reload_tracked_apps()   # трекер должен сразу узнать об изменениях

    def _add_running(self) -> None:
        already_added = {app.process_name for app in usage_tracker.list_tracked_apps()}

        def add(names: list[str]) -> None:
            for name in names:
                try:
                    usage_tracker.add_tracked_app(name)
                except ValueError as exc:
                    w.show_error(str(exc))
            self._load_apps()

        RunningAppsDialog(self, already_added, add)

    def _add_by_name(self) -> None:
        name = w.ask_text("Добавить программу", "Имя процесса, например  code.exe  или  chrome.exe:")
        if not name:
            return
        try:
            usage_tracker.add_tracked_app(name)
        except ValueError as exc:
            w.show_error(str(exc))
            return
        self._load_apps()

    def _selected_app(self):
        app_id = w.selected_id(self.apps_tree)
        if app_id is None:
            w.show_error("Сначала выберите программу в списке.")
        return app_id

    def _toggle_app(self) -> None:
        app_id = w.selected_id(self.apps_tree)
        if app_id is None:
            return
        app = next((a for a in usage_tracker.list_tracked_apps() if a.id == app_id), None)
        if app is not None:
            usage_tracker.set_app_enabled(app_id, not app.enabled)
            self._load_apps()

    def _rename_app(self) -> None:
        app_id = self._selected_app()
        if app_id is None:
            return
        name = w.ask_text("Переименовать", "Новое название:")
        if not name:
            return
        try:
            usage_tracker.rename_app(app_id, name)
        except ValueError as exc:
            w.show_error(str(exc))
            return
        self._load_apps()
        self.refresh()

    def _remove_app(self) -> None:
        app_id = self._selected_app()
        if app_id is None:
            return
        if w.ask_yes_no("Удалить эту программу И всю её записанную историю?"):
            usage_tracker.remove_tracked_app(app_id)
            self._load_apps()
            self.refresh()

    # ------------------------------------------------------- графики и итоги
    def _range_changed(self, label: str) -> None:
        self.days = RANGES[label]
        self.refresh()

    def _auto_refresh(self) -> None:
        """Пока идёт запись, графики обновляются сами каждые 15 секунд."""
        if self.tracker.is_running:
            self.refresh()
        self._job = self.after(15000, self._auto_refresh)

    def refresh(self) -> None:
        start, end = stats.range_for_days(self.days)
        per_app = stats.usage_per_app(start, end)
        # график по дням всегда показываем минимум за неделю - один столбик выглядит странно
        days_start, days_end = stats.range_for_days(max(self.days, 7))
        per_day = stats.usage_per_day(days_start, days_end)
        totals = stats.summary(start, end)

        if totals.most_used_app:
            top = f"{totals.most_used_app} ({stats.format_duration(totals.most_used_seconds)})"
        else:
            top = "-"
        self.summary_label.configure(text=(
            f"Всего: {stats.format_duration(totals.total_seconds)}     "
            f"В среднем за день: {stats.format_duration(totals.daily_average_seconds)}     "
            f"Чаще всего: {top}     Программ: {totals.app_count}"))
        self._draw_charts(per_app, per_day)

    def _draw_charts(self, per_app: list[tuple[str, int]], per_day) -> None:
        """Рисует два графика: время по программам (слева) и время по дням (справа)."""
        dark = ctk.get_appearance_mode() == "Dark"
        if dark:
            background, text_color, edge = "#2b2b2b", "#dce4ee", "#555555"
        else:
            background, text_color, edge = "#ffffff", "#1a1a1a", "#bbbbbb"

        figure = self.figure
        figure.clear()
        figure.patch.set_facecolor(background)
        by_app_ax, by_day_ax = figure.subplots(1, 2)

        for ax in (by_app_ax, by_day_ax):
            ax.set_facecolor(background)
            ax.tick_params(colors=text_color, labelsize=8)
            for spine in ax.spines.values():
                spine.set_color(edge)
            ax.title.set_color(text_color)
            ax.xaxis.label.set_color(text_color)

        # левый график: горизонтальные столбики, самая используемая программа сверху
        by_app_ax.set_title("Время по программам")
        if per_app:
            top_apps = per_app[:8][::-1]
            names = [name for name, _ in top_apps]
            seconds = [secs for _, secs in top_apps]
            divider, unit = _unit(max(seconds))
            bars = by_app_ax.barh(names, [secs / divider for secs in seconds], color="#3b8ed0")
            for bar, secs in zip(bars, seconds):
                # подпись со временем справа от каждого столбика
                by_app_ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2,
                               " " + stats.format_duration(secs), va="center", color=text_color, fontsize=8)
            by_app_ax.set_xlim(0, max(seconds) / divider * 1.35)   # запас справа под подписи
            by_app_ax.set_xlabel(unit)
        else:
            by_app_ax.text(0.5, 0.5, "Данных пока нет.\nДобавьте программы и\nвключите отслеживание.",
                           ha="center", va="center", color=text_color, transform=by_app_ax.transAxes)
            by_app_ax.set_xticks([])
            by_app_ax.set_yticks([])

        # правый график: сколько всего за каждый день
        by_day_ax.set_title("Всего по дням")
        if any(secs for _, secs in per_day):
            divider, unit = _unit(max(secs for _, secs in per_day))
            positions = list(range(len(per_day)))
            by_day_ax.bar(positions, [secs / divider for _, secs in per_day], color="#2fa572")
            step = max(1, math.ceil(len(positions) / 7))   # не больше ~7 подписей дат, чтобы не слипались
            by_day_ax.set_xticks(positions[::step])
            by_day_ax.set_xticklabels([day.strftime("%d.%m") for day, _ in per_day][::step], rotation=0)
            by_day_ax.set_ylabel(unit, color=text_color)
        else:
            by_day_ax.text(0.5, 0.5, "Данных пока нет.", ha="center", va="center", color=text_color,
                           transform=by_day_ax.transAxes)
            by_day_ax.set_xticks([])
            by_day_ax.set_yticks([])
        self.canvas.draw_idle()   # перерисовать, когда у окна будет свободная минута

    # ------------------------------------------------------------------ закрытие
    def shutdown(self) -> None:
        self.after_cancel(self._job)
        if self.tracker.is_running:
            self.tracker.stop()

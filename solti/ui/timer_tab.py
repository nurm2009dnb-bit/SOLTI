"""Раздел "Таймер": секундомер учёбы с целью, история и итоги."""
from __future__ import annotations

import customtkinter as ctk

from ..services import stats_service as stats
from ..services import timer_service as timers
from ..services.timer_service import StudyTimer
from . import widgets as w


def _clock(seconds: int) -> str:
    """Секунды в вид часов: 3725 -> '01:02:05'."""
    hours, rest = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class TimerTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self.timer = StudyTimer()
        self._goal_notified = False   # чтобы звуковой сигнал о цели прозвучал только один раз

        form = ctk.CTkFrame(self)
        form.pack(fill="x", padx=6, pady=(8, 4))
        form.columnconfigure(1, weight=1)
        w.label_row(form, "Над чем работаю").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        self.title_entry = ctk.CTkEntry(form, placeholder_text="например: дипломный проект - трекер")
        self.title_entry.grid(row=0, column=1, padx=8, pady=6, sticky="ew")
        w.label_row(form, "Категория").grid(row=0, column=2, padx=8, pady=6, sticky="w")
        self.category_box = ctk.CTkComboBox(form, values=timers.DEFAULT_CATEGORIES, width=170)
        self.category_box.set(timers.DEFAULT_CATEGORIES[0])
        self.category_box.grid(row=0, column=3, padx=8, pady=6)
        w.label_row(form, "Цель (мин)").grid(row=0, column=4, padx=8, pady=6, sticky="w")
        self.goal_entry = ctk.CTkEntry(form, width=90, placeholder_text="необяз.")
        self.goal_entry.grid(row=0, column=5, padx=8, pady=6)

        self.clock = ctk.CTkLabel(self, text="00:00:00", font=ctk.CTkFont(size=54, weight="bold"))
        self.clock.pack(pady=(10, 0))
        self.start_btn = ctk.CTkButton(self, text="Старт", width=180, height=40,
                                       font=ctk.CTkFont(size=16, weight="bold"), command=self._toggle)
        self.start_btn.pack(pady=6)
        self.info_label = ctk.CTkLabel(self, text="", text_color=w.MUTED_COLOR)
        self.info_label.pack()
        self.totals = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=14))
        self.totals.pack(pady=(8, 0))
        self.categories = ctk.CTkLabel(self, text="", text_color=w.MUTED_COLOR)
        self.categories.pack()

        frame, self.tree = w.make_table(self, [
            ("when", "Начало", 150), ("title", "Что делал", 330), ("cat", "Категория", 150),
            ("dur", "Время", 100, "center")], height=8)
        frame.pack(fill="both", expand=True, padx=6, pady=8)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkButton(bottom, text="Удалить выбранное", width=150, fg_color=w.RED, hover_color=w.RED_HOVER,
                      command=self._delete).pack(side="left", padx=4)
        w.label_row(bottom, "Забыли засечь?  Минут:").pack(side="left", padx=(24, 6))
        self.manual_entry = ctk.CTkEntry(bottom, width=80)
        self.manual_entry.pack(side="left")
        ctk.CTkButton(bottom, text="Добавить сессию (берётся «Над чем работаю» и категория)", width=360,
                      command=self._add_manual).pack(side="left", padx=8)

        self._refresh()
        self._job = self.after(500, self._tick)

    # ---------------------------------------------------------------- действия
    def _toggle(self) -> None:
        if self.timer.is_running:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        try:
            goal = w.parse_int(self.goal_entry.get(), "Цель", default=None, minimum=1)
            self.timer.start(self.title_entry.get(), self.category_box.get(), goal)
        except ValueError as exc:
            w.show_error(str(exc))
            return
        self._goal_notified = False
        self.start_btn.configure(text="Стоп", fg_color=w.RED, hover_color=w.RED_HOVER)
        # пока таймер идёт, название и категорию менять нельзя
        for widget in (self.title_entry, self.category_box, self.goal_entry):
            widget.configure(state="disabled")
        self.info_label.configure(text="Таймер идёт...", text_color=w.OK_COLOR)

    def _stop(self) -> None:
        saved = self.timer.stop()
        self.start_btn.configure(text="Старт", fg_color=w.BLUE, hover_color=w.BLUE_HOVER)
        for widget in (self.title_entry, self.category_box, self.goal_entry):
            widget.configure(state="normal")
        self.clock.configure(text="00:00:00")

        if saved is None:
            self.info_label.configure(text="Сессия короче 5 секунд - не сохранена.", text_color=w.WARN_COLOR)
        else:
            text = f"Сохранено {stats.format_duration(saved.duration_seconds)} - «{saved.title}»."
            # Если в это время работал трекер, покажем, какими программами пользовались
            apps = stats.apps_between(saved.start_time, saved.end_time)
            if apps:
                used = ", ".join(f"{name} {stats.format_duration(seconds)}" for name, seconds in apps)
                text += "  Программы: " + used
            self.info_label.configure(text=text, text_color=w.OK_COLOR)
        self._refresh()

    def _tick(self) -> None:
        """Обновляет часы дважды в секунду, пока таймер идёт."""
        if self.timer.is_running:
            elapsed = self.timer.elapsed_seconds()
            self.clock.configure(text=_clock(elapsed))
            if self.timer.goal_seconds:
                left = self.timer.goal_seconds - elapsed
                if left > 0:
                    self.info_label.configure(text=f"До цели осталось: {stats.format_duration(left)}",
                                              text_color=w.OK_COLOR)
                elif not self._goal_notified:
                    self._goal_notified = True
                    self.bell()   # системный звуковой сигнал
                    self.info_label.configure(text="Цель достигнута! Можно продолжать или остановиться.",
                                              text_color=w.WARN_COLOR)
        self._job = self.after(500, self._tick)

    def _add_manual(self) -> None:
        try:
            minutes = w.parse_int(self.manual_entry.get(), "Минут", minimum=1)
            if minutes is None:
                raise ValueError("Введите количество минут.")
            timers.add_manual_session(self.title_entry.get(), self.category_box.get(), minutes)
        except ValueError as exc:
            w.show_error(str(exc))
            return
        self.manual_entry.delete(0, "end")
        self._refresh()

    def _delete(self) -> None:
        session_id = w.selected_id(self.tree)
        if session_id is None:
            w.show_error("Сначала выберите сессию в таблице.")
            return
        if w.ask_yes_no("Удалить эту сессию?"):
            timers.delete_session(session_id)
            self._refresh()

    # ---------------------------------------------------------------- отображение
    def _refresh(self) -> None:
        """Перерисовывает таблицу истории и итоги за сегодня / неделю."""
        rows = [(str(s.id), (w.fmt_dt(s.start_time), s.title, s.category, stats.format_duration(s.duration_seconds)))
                for s in timers.recent_sessions(100)]
        w.fill_table(self.tree, rows)

        today_start, today_end = stats.range_for_days(1)
        week_start, week_end = stats.range_for_days(7)
        today_total = stats.format_duration(timers.total_seconds(today_start, today_end))
        week_total = stats.format_duration(timers.total_seconds(week_start, week_end))
        self.totals.configure(text=f"Сегодня: {today_total}     За 7 дней: {week_total}")

        per_category = stats.study_per_category(week_start, week_end)
        self.categories.configure(text="  |  ".join(f"{name}: {stats.format_duration(seconds)}"
                                                    for name, seconds in per_category))

    def shutdown(self) -> bool:
        """Вызывается при закрытии окна. Возвращает False, если пользователь передумал закрывать."""
        if self.timer.is_running:
            if not w.ask_yes_no("Таймер ещё идёт.\nСохранить эту сессию и выйти?"):
                return False
            self.timer.stop()
        self.after_cancel(self._job)
        return True

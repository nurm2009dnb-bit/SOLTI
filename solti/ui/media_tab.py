"""Раздел "Списки": аниме, манга, книги и фильмы (поиск, фильтры, добавление, изменение, удаление)."""
from __future__ import annotations

from typing import Optional

import customtkinter as ctk

from ..services import media_service as media
from . import widgets as w

ALL_TYPES = "Все типы"
ALL_STATUSES = "Все статусы"
SORTS = {"Недавно изменённые": "updated", "По названию А-Я": "title",
         "Лучшая оценка": "rating", "Недавно добавленные": "added"}

# Обратные словари: русское название из выпадающего списка -> значение в базе
TYPE_BY_LABEL = {label: value for value, label in media.TYPE_LABELS.items()}
STATUS_BY_LABEL = {label: value for value, label in media.STATUS_LABELS.items()}
TYPE_CHOICES = [media.TYPE_LABELS[value] for value in media.MEDIA_TYPES]
STATUS_CHOICES = [media.STATUS_LABELS[value] for value in media.STATUSES]


class MediaTab(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color="transparent")
        self._selected: Optional[int] = None   # id записи, выбранной в таблице

        # ---- фильтры
        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=6, pady=(8, 4))
        self.search_entry = ctk.CTkEntry(bar, placeholder_text="Поиск по названию или заметкам...", width=280)
        self.search_entry.pack(side="left", padx=8, pady=8)
        self.search_entry.bind("<KeyRelease>", lambda _e: self.refresh())   # ищем прямо во время набора
        self.type_filter = ctk.CTkOptionMenu(bar, values=[ALL_TYPES] + TYPE_CHOICES, width=120,
                                             command=lambda _v: self.refresh())
        self.type_filter.pack(side="left", padx=4)
        self.status_filter = ctk.CTkOptionMenu(bar, values=[ALL_STATUSES] + STATUS_CHOICES, width=140,
                                               command=lambda _v: self.refresh())
        self.status_filter.pack(side="left", padx=4)
        self.sort_menu = ctk.CTkOptionMenu(bar, values=list(SORTS), width=190, command=lambda _v: self.refresh())
        self.sort_menu.pack(side="left", padx=4)
        self.count_label = ctk.CTkLabel(bar, text="", text_color=w.MUTED_COLOR)
        self.count_label.pack(side="right", padx=12)

        # ---- таблица
        frame, self.tree = w.make_table(self, [
            ("type", "Тип", 80), ("title", "Название", 300), ("status", "Статус", 110),
            ("progress", "Прогресс", 100, "center"), ("rating", "Оценка", 70, "center"),
            ("updated", "Изменено", 140)], height=10)
        frame.pack(fill="both", expand=True, padx=6)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # ---- форма
        form = ctk.CTkFrame(self)
        form.pack(fill="x", padx=6, pady=8)
        form.columnconfigure((1, 3, 5), weight=1)
        self.f_type = ctk.CTkOptionMenu(form, values=TYPE_CHOICES, width=120, command=lambda _v: self._unit_hint())
        self.f_title = ctk.CTkEntry(form, placeholder_text="Название")
        self.f_status = ctk.CTkOptionMenu(form, values=STATUS_CHOICES, width=140)
        self.f_progress = ctk.CTkEntry(form, width=80, placeholder_text="0")
        self.f_total = ctk.CTkEntry(form, width=80, placeholder_text="неизв.")
        self.f_rating = ctk.CTkEntry(form, width=80, placeholder_text="0-10")
        self.f_notes = ctk.CTkTextbox(form, height=54)
        self.progress_label = w.label_row(form, "Прогресс")
        self.total_label = w.label_row(form, "из")

        w.label_row(form, "Тип").grid(row=0, column=0, padx=8, pady=4, sticky="w")
        self.f_type.grid(row=0, column=1, padx=8, pady=4, sticky="w")
        w.label_row(form, "Название").grid(row=0, column=2, padx=8, pady=4, sticky="w")
        self.f_title.grid(row=0, column=3, columnspan=3, padx=8, pady=4, sticky="ew")
        w.label_row(form, "Статус").grid(row=1, column=0, padx=8, pady=4, sticky="w")
        self.f_status.grid(row=1, column=1, padx=8, pady=4, sticky="w")
        self.progress_label.grid(row=1, column=2, padx=8, pady=4, sticky="w")
        self.f_progress.grid(row=1, column=3, padx=8, pady=4, sticky="w")
        self.total_label.grid(row=1, column=4, padx=8, pady=4, sticky="e")
        self.f_total.grid(row=1, column=5, padx=8, pady=4, sticky="w")
        w.label_row(form, "Оценка").grid(row=2, column=0, padx=8, pady=4, sticky="w")
        self.f_rating.grid(row=2, column=1, padx=8, pady=4, sticky="w")
        w.label_row(form, "Заметки").grid(row=2, column=2, padx=8, pady=4, sticky="nw")
        self.f_notes.grid(row=2, column=3, columnspan=3, padx=8, pady=4, sticky="ew")

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=6, pady=(0, 6))
        ctk.CTkButton(buttons, text="Добавить", width=100, command=self._add).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Сохранить изменения", width=160, command=self._update).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="+1 к прогрессу", width=120, fg_color=w.GREEN, hover_color=w.GREEN_HOVER,
                      command=self._plus_one).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Удалить", width=90, fg_color=w.RED, hover_color=w.RED_HOVER,
                      command=self._delete).pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="Очистить форму", width=130, fg_color=w.GRAY, hover_color=w.GRAY_HOVER,
                      command=self._clear).pack(side="left", padx=4)

        self._unit_hint()
        self.refresh()

    # ---------------------------------------------------------------- помощники
    def _selected_type(self) -> str:
        """Тип из формы во внутреннем виде (anime / manga / book / film)."""
        return TYPE_BY_LABEL[self.f_type.get()]

    def _unit_hint(self) -> None:
        """Подпись у прогресса зависит от типа: серии, главы, страницы или части."""
        self.progress_label.configure(text=media.PROGRESS_UNIT[self._selected_type()])
        self.total_label.configure(text="из")

    def _read_form(self) -> dict:
        """Собирает данные формы в словарь с именами параметров add_item / update_item."""
        return dict(
            media_type=self._selected_type(),
            title=self.f_title.get(),
            status=STATUS_BY_LABEL[self.f_status.get()],
            progress=w.parse_int(self.f_progress.get(), "Прогресс", default=0, minimum=0),
            total=w.parse_int(self.f_total.get(), "Всего", default=None, minimum=1),
            rating=w.parse_int(self.f_rating.get(), "Оценка", default=None, minimum=0),
            notes=self.f_notes.get("1.0", "end").strip(),
        )

    def _fill_form(self, item) -> None:
        self.f_type.set(media.TYPE_LABELS[item.type])
        w.set_entry(self.f_title, item.title)
        self.f_status.set(media.STATUS_LABELS[item.status])
        w.set_entry(self.f_progress, str(item.progress))
        w.set_entry(self.f_total, "" if item.total is None else str(item.total))
        w.set_entry(self.f_rating, "" if item.rating is None else str(item.rating))
        self.f_notes.delete("1.0", "end")
        self.f_notes.insert("1.0", item.notes or "")
        self._unit_hint()

    def _clear(self) -> None:
        self._selected = None
        if self.tree.selection():
            self.tree.selection_remove(*self.tree.selection())
        for entry in (self.f_title, self.f_progress, self.f_total, self.f_rating):
            entry.delete(0, "end")
        self.f_notes.delete("1.0", "end")
        self.f_status.set(media.STATUS_LABELS["planned"])

    # ---------------------------------------------------------------- таблица
    def refresh(self) -> None:
        type_label = self.type_filter.get()
        status_label = self.status_filter.get()
        items = media.search_items(
            self.search_entry.get(),
            media_type=None if type_label == ALL_TYPES else TYPE_BY_LABEL[type_label],
            status=None if status_label == ALL_STATUSES else STATUS_BY_LABEL[status_label],
            sort=SORTS[self.sort_menu.get()],
        )
        rows = []
        for item in items:
            progress = f"{item.progress}/{item.total}" if item.total else str(item.progress)
            rating = "" if item.rating is None else item.rating
            rows.append((str(item.id), (media.TYPE_LABELS[item.type], item.title, media.STATUS_LABELS[item.status],
                                        progress, rating, w.fmt_dt(item.updated_at))))
        w.fill_table(self.tree, rows)
        self.count_label.configure(text=f"Записей: {len(items)}")

    def _on_select(self, _event=None) -> None:
        item_id = w.selected_id(self.tree)
        if item_id is None:
            return
        item = media.get_item(item_id)
        if item is not None:
            self._selected = item_id
            self._fill_form(item)

    # ---------------------------------------------------------------- действия
    def _add(self) -> None:
        try:
            media.add_item(**self._read_form())
        except ValueError as exc:
            w.show_error(str(exc))
            return
        self._clear()
        self.refresh()

    def _update(self) -> None:
        if self._selected is None:
            w.show_error("Сначала выберите запись в таблице.")
            return
        try:
            media.update_item(self._selected, **self._read_form())
        except ValueError as exc:
            w.show_error(str(exc))
            return
        self.refresh()

    def _plus_one(self) -> None:
        if self._selected is None:
            w.show_error("Сначала выберите запись в таблице.")
            return
        try:
            item = media.increment_progress(self._selected)
        except ValueError as exc:
            w.show_error(str(exc))
            return
        self._fill_form(item)
        self.refresh()

    def _delete(self) -> None:
        if self._selected is None:
            w.show_error("Сначала выберите запись в таблице.")
            return
        if w.ask_yes_no("Удалить эту запись навсегда?"):
            media.delete_item(self._selected)
            self._clear()
            self.refresh()

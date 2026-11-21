"""
Главное окно SOLTI: боковая панель слева, разделы справа и аккуратное закрытие.

Боковая панель:
  * логотип (планета с кольцами) и название программы
  * кнопки разделов: Сортировка, Трекер, Пароли, Списки, Таймер
  * внизу - переключатель светлой/тёмной темы и кнопка "Выход"

Все разделы создаются один раз при запуске, а при переключении мы просто
прячем один и показываем другой. Поэтому слежение за папкой, трекер и таймер
продолжают работать, даже когда открыт другой раздел.
"""
from __future__ import annotations

import logging
import tkinter as tk
import customtkinter as ctk
import traceback   # чтобы записать в журнал полный текст ошибки
from .. import config, logo
from . import widgets as w
from ..services import settings_service as settings
from .media_tab import MediaTab
from .sorter_tab import SorterTab
from .timer_tab import TimerTab
from .usage_tab import UsageTab
from .vault_tab import VaultTab

log = logging.getLogger(__name__)

SIDEBAR_WIDTH = 220

# (ключ раздела, надпись на кнопке) - в том порядке, в котором кнопки идут на панели
SECTIONS = [
    ("sorter", "Сортировщик файлов"),
    ("usage", "Трекер приложений"),
    ("vault", "Пароли"),
    ("media", "Списки"),
    ("timer", "Таймер"),
]

class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(config.APP_TITLE)   # "SOLTI 2.2.1"
        self.geometry("1340x800")
        self.minsize(1220, 720)

        self._apply_saved_theme()
        self._set_window_icon()
        w.setup_ttk_style()

        # Сетка окна: колонка 0 - боковая панель фиксированной ширины, колонка 1 - всё остальное
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()

        self.content = ctk.CTkFrame(self, corner_radius=5)
        self.content.grid(row=0, column=1, sticky="nsew", padx=(0, 12), pady=12)

        self.sorter_tab = SorterTab(self.content)
        self.usage_tab = UsageTab(self.content)
        self.vault_tab = VaultTab(self.content)
        self.media_tab = MediaTab(self.content)
        self.timer_tab = TimerTab(self.content)
        self.pages = {
            "sorter": self.sorter_tab,
            "usage": self.usage_tab,
            "vault": self.vault_tab,
            "media": self.media_tab,
            "timer": self.timer_tab,
        }
        self.current_page = ""
        self.show_page("sorter")

        # Крестик в углу окна работает так же, как кнопка "Выход"
        self.protocol("WM_DELETE_WINDOW", self.close)

    # ---------------------------------------------------------------- боковая панель
    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self, width=SIDEBAR_WIDTH, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)   # не даём панели растягиваться под содержимое
        sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar = sidebar

        # CTkImage сам подставляет картинку нужного размера с учётом масштаба экрана Windows
        logo_image = logo.draw_saturn(256)
        self.logo_image = ctk.CTkImage(light_image=logo_image, dark_image=logo_image, size=(110, 110))
        ctk.CTkLabel(sidebar, image=self.logo_image, text="").grid(row=0, column=0, pady=(22, 4))
        ctk.CTkLabel(sidebar, text=config.APP_NAME,
                     font=ctk.CTkFont(size=28, weight="bold")).grid(row=1, column=0)
        ctk.CTkLabel(sidebar, text=f"версия {config.APP_VERSION}",
                     text_color=w.MUTED_COLOR).grid(row=2, column=0, pady=(0, 18))

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for row, (key, label) in enumerate(SECTIONS, start=3):
            button = ctk.CTkButton(
                sidebar, text=label, anchor="w", height=42, corner_radius=8,
                font=ctk.CTkFont(size=14),
                fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray75", "gray28"),
                # key=key "запоминает" текущий ключ - без этого все кнопки открывали бы последний раздел
                command=lambda key=key: self.show_page(key),
            )
            button.grid(row=row, column=0, sticky="ew", padx=12, pady=3)
            self.nav_buttons[key] = button

        # Пустая строка с весом 1 "расталкивает" кнопки: разделы сверху, тема и выход снизу
        spacer_row = 3 + len(SECTIONS)
        sidebar.grid_rowconfigure(spacer_row, weight=1)

        self.theme_btn = ctk.CTkButton(sidebar, text="", height=36, fg_color=w.GRAY, hover_color=w.GRAY_HOVER,
                                       command=self.toggle_theme)
        self.theme_btn.grid(row=spacer_row + 1, column=0, sticky="ew", padx=12, pady=(0, 6))
        self._update_theme_button()

        ctk.CTkButton(sidebar, text="Выход", height=36, fg_color=w.RED, hover_color=w.RED_HOVER,
                      command=self.close).grid(row=spacer_row + 2, column=0, sticky="ew", padx=12, pady=(0, 16))

    def show_page(self, key: str) -> None:
        """Показывает нужный раздел и подсвечивает его кнопку на панели."""
        if key == self.current_page:
            return
        for page in self.pages.values():
            page.pack_forget()
        self.pages[key].pack(fill="both", expand=True, padx=8, pady=8)
        self.current_page = key

        for button_key, button in self.nav_buttons.items():
            if button_key == key:
                button.configure(fg_color=w.BLUE, text_color="white")
            else:
                button.configure(fg_color="transparent", text_color=("gray10", "gray90"))

    # ---------------------------------------------------------------- тема и иконка
    def _apply_saved_theme(self) -> None:
        """Если пользователь уже выбирал тему - включаем её. Иначе остаётся тема Windows."""
        saved = settings.get_setting("theme", "")
        if saved in ("Light", "Dark"):
            ctk.set_appearance_mode(saved)

    def toggle_theme(self) -> None:
        """Переключает светлую и тёмную тему и запоминает выбор."""
        new_mode = "Light" if ctk.get_appearance_mode() == "Dark" else "Dark"
        ctk.set_appearance_mode(new_mode)
        settings.set_setting("theme", new_mode)
        # Виджеты CustomTkinter перекрашиваются сами, а таблицы и графики - нет:
        w.setup_ttk_style()
        self.usage_tab.refresh()
        self._update_theme_button()

    def _update_theme_button(self) -> None:
        # Кнопка подписана тем, НА ЧТО она переключит
        if ctk.get_appearance_mode() == "Dark":
            self.theme_btn.configure(text="☀  Светлая тема")
        else:
            self.theme_btn.configure(text="☾  Тёмная тема")

    def _set_window_icon(self) -> None:
        """Ставит логотип в заголовок окна и на панель задач."""
        try:
            icon_file = logo.ensure_icon_file(config.ICON_PATH)
            # iconbitmap, а не iconphoto: иначе CustomTkinter через долю секунды поставит свою иконку
            self.iconbitmap(str(icon_file))
        except (tk.TclError, OSError):
            log.warning("Не удалось установить иконку окна", exc_info=True)   # не страшно, работаем дальше

    # ---------------------------------------------------------------- ошибки и выход
    def report_callback_exception(self, exc, val, tb) -> None:
        """Любая неожиданная ошибка в кнопке записывается в журнал и показывается, а не теряется молча."""
        log.error("Ошибка интерфейса:\n%s", "".join(traceback.format_exception(exc, val, tb)))
        w.show_error(f"Что-то пошло не так:\n{val}\n\nПодробности записаны в файл:\n{config.LOG_PATH}")

    def close(self) -> None:
        """Аккуратный выход: сохранить таймер, остановить слежение и трекер, закрыть хранилище."""
        if not self.timer_tab.shutdown():
            return   # пользователь решил не останавливать идущий таймер
        self.sorter_tab.shutdown()
        self.usage_tab.shutdown()
        self.vault_tab.shutdown()
        self.destroy()

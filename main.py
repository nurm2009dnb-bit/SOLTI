"""Точка входа: отсюда запускается SOLTI 2.2.1  ->  python main.py"""
import logging
import sys
import customtkinter as ctk

from solti import config
from solti.database.base import init_db


def main() -> None:
    # Журнал ошибок пишется в файл solti.log в папке данных (кодировка utf-8 - из-за русского текста)
    logging.basicConfig(filename=config.LOG_PATH, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        init_db()
        ctk.set_appearance_mode("System")       # по умолчанию тема как в Windows (потом можно переключить)
        ctk.set_default_color_theme("blue")
        # Окно импортируем только здесь, после подключения базы: разделы читают настройки уже при создании
        from solti.ui.app_window import App
        App().mainloop()
    except Exception:
        logging.exception("Критическая ошибка")
        raise


if __name__ == "__main__":
    sys.exit(main())

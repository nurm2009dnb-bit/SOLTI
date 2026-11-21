"""Общие настройки программы: название, версия и где лежат данные.

База данных и журнал (лог) хранятся в папке пользователя AppData, поэтому
программа работает одинаково, из какой бы папки её ни запустили.
Если задать переменную окружения SOLTI_DATA_DIR, данные будут храниться там
(это нужно тестам, чтобы они не трогали настоящую базу).
"""
from __future__ import annotations

import os                 # чтение переменных окружения (APPDATA, SOLTI_DATA_DIR)
from pathlib import Path  # удобная и кроссплатформенная работа с путями

APP_NAME = "SOLTI"
APP_VERSION = "2.2.1"
APP_TITLE = f"{APP_NAME} {APP_VERSION}"   # то, что видно в заголовке окна

# У этой версии своя папка с данными. Так старые версии программы
# и их базы остаются нетронутыми.
DATA_FOLDER_NAME = "SOLTI_2.2.1"


def _find_data_folder() -> Path:
    """Выбирает папку для данных и создаёт её, если её ещё нет."""
    custom_folder = os.environ.get("SOLTI_DATA_DIR")
    if custom_folder:
        folder = Path(custom_folder)
    else:
        appdata = os.environ.get("APPDATA")  # есть только в Windows
        if appdata:
            folder = Path(appdata) / DATA_FOLDER_NAME
        else:
            # на Linux/macOS (например, при разработке) кладём данные в домашнюю папку
            folder = Path.home() / ".solti_2.2.1"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


DATA_DIR: Path = _find_data_folder()
DB_PATH: Path = DATA_DIR / "solti.db"
DATABASE_URL: str = f"sqlite:///{DB_PATH.as_posix()}"   # адрес базы в формате SQLAlchemy
LOG_PATH: Path = DATA_DIR / "solti.log"
ICON_PATH: Path = DATA_DIR / "solti.ico"                # иконка окна (рисуется при первом запуске)

# Папка, которую сортировщик предлагает по умолчанию
DEFAULT_WATCH_FOLDER: Path = Path.home() / "Downloads"

# Трекер приложений
TRACK_POLL_SECONDS = 2          # как часто проверяем, какое окно сейчас активно
TRACK_FLUSH_SECONDS = 60        # длинный отрезок работы сохраняем в базу хотя бы раз в минуту
DEFAULT_IDLE_MINUTES = 3        # столько минут без мыши и клавиатуры = пользователь отошёл

# Хранилище паролей
VAULT_AUTOLOCK_MINUTES = 5      # автоблокировка при бездействии
CLIPBOARD_CLEAR_SECONDS = 15    # через сколько секунд стереть скопированный пароль

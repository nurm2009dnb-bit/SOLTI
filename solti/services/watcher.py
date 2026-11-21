"""Следит за папкой и сам сортирует новые файлы.

Почему важен on_moved: браузер качает файл как "file.crdownload", а когда закончит -
ПЕРЕИМЕНОВЫВАЕТ его. Для системы это событие "перемещение", а не "создание",
поэтому обрабатываем оба. Вся работа идёт в одном отдельном потоке, чтобы не
задерживать поток библиотеки watchdog.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor   # готовый "работник" в отдельном потоке с очередью задач
from pathlib import Path
from typing import Callable, Optional

# watchdog - библиотека, которая получает от Windows события "файл создан/переименован"
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from . import sorter

log = logging.getLogger(__name__)


def wait_until_stable(path: Path, timeout: float = 60.0, interval: float = 0.5) -> bool:
    """Ждёт, пока файл перестанет расти (докачался). False - если не дождались или файл исчез."""
    deadline = time.monotonic() + timeout
    last_size = -1
    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == last_size:
            return True   # размер не изменился за interval секунд - файл готов
        last_size = size
        time.sleep(interval)
    return False


class _Handler(FileSystemEventHandler):
    """Получает события от watchdog и передаёт новые файлы наблюдателю."""

    def __init__(self, watcher: "FolderWatcher"):
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher.submit(Path(str(event.src_path)))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._watcher.submit(Path(str(event.dest_path)))   # нас интересует новое имя файла


class FolderWatcher:
    def __init__(self, folder: Path,
                 on_result: Optional[Callable[[sorter.MoveResult], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None):
        self.folder = Path(folder)
        self._on_result = on_result     # кого позвать, когда файл перемещён (окно обновит таблицу)
        self._on_error = on_error
        self._observer: Optional[Observer] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._pending: set[Path] = set()   # файлы, которые уже в очереди - чтобы не взять один файл дважды
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._observer is not None and self._observer.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        if not self.folder.is_dir():
            raise FileNotFoundError(f"Папка не существует: {self.folder}")
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sorter")
        self._observer = Observer()
        # recursive=False: смотрим только саму папку, а не подпапки, куда мы сами раскладываем файлы
        self._observer.schedule(_Handler(self), str(self.folder), recursive=False)
        self._observer.start()
        log.info("Слежу за папкой %s", self.folder)

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        log.info("Перестал следить за папкой %s", self.folder)

    # вызывается из потока watchdog
    def submit(self, path: Path) -> None:
        if path.parent != self.folder and path.parent.resolve() != self.folder.resolve():
            return  # файл переместили в подпапку (это наша же сортировка) - пропускаем
        if sorter.is_ignored(path) or self._executor is None:
            return
        with self._lock:
            if path in self._pending:
                return
            self._pending.add(path)
        self._executor.submit(self._process, path)

    def _process(self, path: Path) -> None:
        """Работает в отдельном потоке: дождаться конца загрузки и отсортировать файл."""
        try:
            if not wait_until_stable(path):
                return
            result = sorter.sort_file(path, self.folder)
            if result and self._on_result:
                self._on_result(result)
        except Exception as exc:  # один "плохой" файл не должен остановить всю слежку
            log.exception("Не удалось отсортировать %s", path)
            if self._on_error:
                self._on_error(f"{path.name}: {exc}")
        finally:
            with self._lock:
                self._pending.discard(path)

"""
Умный сортировщик файлов.
Как выбирается папка для файла (побеждает первое совпадение):
  1. Правила пользователя из базы, начиная с самого высокого приоритета.
     Правило срабатывает, когда совпали ВСЕ его заполненные части:
     ключевое слово в имени файла И/ИЛИ расширение.
  2. Встроенная таблица расширений (Изображения, Видео, Документы, Код/Python...).
  3. Ничего не подошло - файл остаётся на месте.

Безопасность:
  1.недокачанные файлы (.crdownload, .part, .tmp...) и скрытые файлы пропускаются
  2.файл никогда не перезаписывается: если в папке уже есть файл с таким же
    именем, к имени нового добавляется дата перемещения - "отчёт (14.11.2026).pdf"
  3.каждое перемещение записывается в базу, поэтому его можно отменить
"""
from __future__ import annotations
import shutil                          # перемещение файлов (умеет переносить и между дисками)
from dataclasses import dataclass      # короткая запись простых классов-"контейнеров" для данных
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from sqlalchemy import select
from ..database.base import session_scope
from ..database.models import SortLog, SortRule

# ------------------------------------------------------- встроенная таблица расширений
EXTENSION_FOLDERS: dict[str, list[str]] = {
    "Изображения": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".heic", ".ico"],
    "Видео": [".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv"],
    "Аудио": [".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"],
    "Документы": [".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".md", ".text"],
    "Таблицы": [".xls", ".xlsx", ".csv", ".ods"],
    "Презентации": [".ppt", ".pptx", ".odp", ".key"],
    "Книги": [".epub", ".fb2", ".mobi", ".djvu"],
    "Архивы": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"],
    "Установщики": [".exe", ".msi", ".dmg", ".pkg", ".deb", ".apk"],
    "Код/Python": [".py", ".ipynb"],
    "Код/CSharp": [".cs", ".csproj", ".sln"],
    "Код/Web": [".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx", ".json"],
    "Код/C_CPP": [".c", ".cpp", ".h", ".hpp"],
    "Код/Java": [".java", ".jar"],
    "Код/Другое": [".sql", ".sh", ".bat", ".ps1", ".go", ".rs", ".php"],
}
# Обратная таблица "расширение -> папка", чтобы искать папку за один шаг
FOLDER_BY_EXTENSION = {ext: folder for folder, extensions in EXTENSION_FOLDERS.items() for ext in extensions}

# Файлы, которые ещё качаются или временные - их трогать нельзя
PARTIAL_EXTENSIONS = {".crdownload", ".part", ".tmp", ".temp", ".download", ".opdownload", ".partial"}

# -------------------------------------------------------------- классы для данных
@dataclass(frozen=True)
class RuleData:
    """Копия правила из базы. Ей можно пользоваться вне сессии базы, и её легко тестировать."""
    name: str
    keywords: tuple[str, ...]
    extensions: tuple[str, ...]
    target_folder: str
    priority: int = 0

@dataclass(frozen=True)
class Classification:
    """Решение сортировщика: куда положить файл и почему."""
    folder: str      # путь относительно сортируемой папки, например "Учёба/Домашние задания"
    reason: str      # понятное объяснение: 'правило «Домашние задания»' или 'расширение .pdf'

@dataclass(frozen=True)
class MoveResult:
    """Что произошло с одним файлом после перемещения."""
    source: Path
    destination: Path
    folder: str
    reason: str
    log_id: Optional[int] = None

# ---------------------------------------------------- вспомогательные функции
def split_list(text: str) -> tuple[str, ...]:
    """'Домашка, Lab ,hw' -> ('домашка', 'lab', 'hw')"""
    parts = text.replace(";", ",").split(",")
    return tuple(part.strip().lower() for part in parts if part.strip())

def normalize_extensions(text: str) -> tuple[str, ...]:
    """'pdf, .DOCX' -> ('.pdf', '.docx') - точку в начале добавляем сами, если её забыли."""
    return tuple(ext if ext.startswith(".") else "." + ext for ext in split_list(text))

def clean_folder(text: str) -> str:
    """
    Делает безопасный относительный путь: без буквы диска, без '..' и без слэша в начале.
    Это защита от правила вроде '../../Windows', которое увело бы файлы за пределы папки.
    """
    parts = [part.strip() for part in text.replace("\\", "/").split("/")]
    safe_parts = [part for part in parts if part and part not in (".", "..") and ":" not in part]
    return "/".join(safe_parts)

def load_rules() -> list[RuleData]:
    """Читает включённые правила из базы, от высокого приоритета к низкому."""
    with session_scope() as s:
        rows = s.scalars(
            select(SortRule)
            .where(SortRule.enabled.is_(True))
            .order_by(SortRule.priority.desc(), SortRule.id)
        ).all()
        return [
            RuleData(row.name, split_list(row.keywords), normalize_extensions(row.extensions), clean_folder(row.target_folder), row.priority)
            for row in rows
        ]

def is_ignored(path: Path) -> bool:
    """True для файлов, которые сортировать нельзя: скрытые, временные, системные."""
    name = path.name
    return (
        name.startswith(".")
        or name.startswith("~$")                 # временные файлы-блокировки Word/Excel
        or path.suffix.lower() in PARTIAL_EXTENSIONS
        or name.lower() in {"desktop.ini", "thumbs.db"}
    )

# -------------------------------------------------- выбор папки
def classify(filename: str, rules: Iterable[RuleData]) -> Optional[Classification]:
    """Решает, в какую папку отправить файл. Только по имени, диск не трогает."""
    path = Path(filename)
    name_lower = path.stem.lower()
    extension = path.suffix.lower()

    for rule in rules:  # правила уже отсортированы по приоритету
        if not rule.target_folder:
            continue
        if not rule.keywords and not rule.extensions:
            continue  # пустое правило подошло бы к любому файлу - пропускаем его
        keyword_matches = not rule.keywords or any(word in name_lower for word in rule.keywords)
        extension_matches = not rule.extensions or extension in rule.extensions
        if keyword_matches and extension_matches:
            return Classification(rule.target_folder, f"правило «{rule.name}»")

    folder = FOLDER_BY_EXTENSION.get(extension)
    if folder:
        return Classification(folder, f"расширение {extension}")
    return None

def unique_destination(folder: Path, filename: str) -> Path:
    """
    report.pdf -> report (1).pdf -> report (2).pdf ... - никогда не перезаписываем файл.
    Используется при отмене, когда файл возвращается на старое место.
    """
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem, suffix = Path(filename).stem, Path(filename).suffix
    number = 1
    while True:
        candidate = folder / f"{stem} ({number}){suffix}"
        if not candidate.exists():
            return candidate
        number += 1

def dated_destination(folder: Path, filename: str, moved_at: Optional[datetime] = None) -> Path:
    """
    Куда положить файл при сортировке.
    Если в папке нет файла с таким именем - имя не меняется.
    Только если такой файл уже есть, к имени добавляется дата перемещения:
    отчёт.pdf -> отчёт (14.11.2026).pdf
    Если и это имя занято (два одинаковых файла за день) - добавляем ещё и время,
    а в самом крайнем случае - номер.
    """
    candidate = folder / filename
    if not candidate.exists():
        return candidate

    moved_at = moved_at or datetime.now()
    stem, suffix = Path(filename).stem, Path(filename).suffix
    with_date = folder / f"{stem} ({moved_at:%d.%m.%Y}){suffix}"
    if not with_date.exists():
        return with_date

    # двоеточие в имени файла Windows не разрешает, поэтому время пишем через дефис
    with_time = folder / f"{stem} ({moved_at:%d.%m.%Y %H-%M-%S}){suffix}"
    if not with_time.exists():
        return with_time

    return unique_destination(folder, with_time.name)


# ------------------------------------------------------------------- действия
def preview(source_dir: Path, rules: Optional[list[RuleData]] = None) -> list[tuple[Path, Classification]]:
    """Показывает, что БУДЕТ перемещено. Сами файлы не трогаются."""
    rules = load_rules() if rules is None else rules
    plan = []
    for item in sorted(Path(source_dir).iterdir()):
        if item.is_file() and not is_ignored(item):
            decision = classify(item.name, rules)
            if decision:
                plan.append((item, decision))
    return plan


def sort_file(path: Path, source_dir: Path, rules: Optional[list[RuleData]] = None) -> Optional[MoveResult]:
    """Перемещает один файл в его папку. Возвращает None, если ничего не сделано."""
    path, source_dir = Path(path), Path(source_dir)
    if not path.is_file() or is_ignored(path):
        return None
    if path.parent.resolve() != source_dir.resolve():
        return None  # трогаем только файлы, лежащие прямо в выбранной папке

    rules = load_rules() if rules is None else rules
    decision = classify(path.name, rules)
    if decision is None:
        return None

    target_dir = source_dir / decision.folder
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = dated_destination(target_dir, path.name)
    shutil.move(str(path), str(destination))

    # Записываем перемещение в журнал, чтобы его можно было отменить
    with session_scope() as s:
        entry = SortLog(file_name=destination.name, original_path=str(path),
                        new_path=str(destination), reason=decision.reason)
        s.add(entry)
        s.flush()
        log_id = entry.id
    return MoveResult(path, destination, decision.folder, decision.reason, log_id)


def sort_folder(source_dir: Path) -> list[MoveResult]:
    """Сортирует все файлы, которые сейчас лежат в папке."""
    rules = load_rules()   # читаем правила один раз, а не для каждого файла
    results = []
    for item in sorted(Path(source_dir).iterdir()):
        try:
            result = sort_file(item, source_dir, rules)
        except OSError:
            continue  # файл открыт в другой программе или нет прав - пропускаем и идём дальше
        if result:
            results.append(result)
    return results


# --------------------------------------------------------------------- журнал
def recent_log(limit: int = 100) -> list[SortLog]:
    with session_scope() as s:
        return list(s.scalars(select(SortLog).order_by(SortLog.id.desc()).limit(limit)).all())


def undo(log_id: int) -> Path:
    """Возвращает отсортированный файл на старое место. Возвращает путь, куда он вернулся."""
    with session_scope() as s:
        entry = s.get(SortLog, log_id)
        if entry is None:
            raise ValueError("Запись в журнале не найдена.")
        if entry.undone:
            raise ValueError("Это перемещение уже отменено.")
        current, original = Path(entry.new_path), Path(entry.original_path)
        if not current.exists():
            raise FileNotFoundError(f"Файла больше нет по адресу {current}")
        original.parent.mkdir(parents=True, exist_ok=True)
        restored = unique_destination(original.parent, original.name)
        shutil.move(str(current), str(restored))
        entry.undone = True
        return restored


def undo_last() -> Path:
    """Отменяет самое последнее (ещё не отменённое) перемещение."""
    with session_scope() as s:
        entry = s.scalars(
            select(SortLog).where(SortLog.undone.is_(False)).order_by(SortLog.id.desc())
        ).first()
        if entry is None:
            raise ValueError("Нечего отменять.")
        log_id = entry.id
    return undo(log_id)


# ------------------------------------------------------- правила: добавить/изменить/удалить
def list_rules() -> list[SortRule]:
    with session_scope() as s:
        return list(s.scalars(select(SortRule).order_by(SortRule.priority.desc(), SortRule.id)).all())


def _check_rule(name: str, keywords: str, extensions: str, folder: str) -> str:
    """Проверяет поля правила и возвращает очищенный путь к папке."""
    if not name.strip():
        raise ValueError("Укажите название правила.")
    if not keywords.strip() and not extensions.strip():
        raise ValueError("Укажите хотя бы одно ключевое слово или одно расширение.")
    cleaned = clean_folder(folder)
    if not cleaned:
        raise ValueError("Укажите папку назначения (например: Учёба/Домашние задания).")
    return cleaned


def add_rule(name: str, keywords: str, extensions: str, folder: str, priority: int = 0, enabled: bool = True) -> int:
    cleaned_folder = _check_rule(name, keywords, extensions, folder)
    with session_scope() as s:
        rule = SortRule(name=name.strip(), keywords=keywords.strip(), extensions=extensions.strip(),
                        target_folder=cleaned_folder, priority=priority, enabled=enabled)
        s.add(rule)
        s.flush()
        return rule.id


def update_rule(rule_id: int, name: str, keywords: str, extensions: str, folder: str,
                priority: int = 0, enabled: bool = True) -> None:
    cleaned_folder = _check_rule(name, keywords, extensions, folder)
    with session_scope() as s:
        rule = s.get(SortRule, rule_id)
        if rule is None:
            raise ValueError("Правило не найдено.")
        rule.name = name.strip()
        rule.keywords = keywords.strip()
        rule.extensions = extensions.strip()
        rule.target_folder = cleaned_folder
        rule.priority = priority
        rule.enabled = enabled


def delete_rule(rule_id: int) -> None:
    with session_scope() as s:
        rule = s.get(SortRule, rule_id)
        if rule is not None:
            s.delete(rule)

"""
Списки аниме, манги, книг и фильмов: добавить, найти, изменить, удалить.
В базе тип и статус хранятся короткими английскими словами (anime, planned...),
а в окне показываются русские названия из словарей ниже. Так база не зависит
от языка интерфейса.
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy import or_, select   # or_ - условие "ИЛИ" в запросе (поиск по названию ИЛИ заметкам)
from ..database.base import session_scope
from ..database.models import MediaItem

MEDIA_TYPES = ["anime", "manga", "book", "film"]
STATUSES = ["planned", "in progress", "completed", "dropped"]

# Что видит пользователь вместо внутренних значений
TYPE_LABELS = {
    "anime": "Аниме",
    "manga": "Манга",
    "book": "Книга",
    "film": "Фильм",
}
STATUS_LABELS = {
    "planned": "В планах",
    "in progress": "В процессе",
    "completed": "Завершено",
    "dropped": "Брошено",
}
PROGRESS_UNIT = {
    "anime": "Серии",
    "manga": "Главы",
    "book": "Страницы",
    "film": "Части",
}

def _check_fields(media_type: str, title: str, status: str, progress: int, total: Optional[int], rating: Optional[int]) -> None:
    """Проверяет данные перед сохранением. При ошибке бросает ValueError с понятным текстом"""
    if media_type not in MEDIA_TYPES:
        raise ValueError("Тип не указан. Выберите: аниме, манга, книга или фильм")
    if not title.strip():
        raise ValueError("Введите название")
    if status not in STATUSES:
        raise ValueError("Выберите статус")
    if progress < 0:
        raise ValueError("Прогресс не может быть отрицательным")
    if total is not None and total <= 0:
        raise ValueError("Всего должно быть положительным числом (или оставьте поле пустым)")
    if total is not None and progress > total:
        raise ValueError("Прогресс не может быть больше, чем всего")
    if rating is not None and not 0 <= rating <= 10:
        raise ValueError("Оценка должна быть от 0 до 10")

def add_item(media_type: str, title: str, status: str = "planned", progress: int = 0, total: Optional[int] = None, rating: Optional[int] = None, notes: str = "") -> int:
    """Добавляет запись и возвращает её id."""
    _check_fields(media_type, title, status, progress, total, rating)
    with session_scope() as s:
        item = MediaItem(type=media_type, title=title.strip(), status=status, progress=progress, total=total, rating=rating, notes=notes.strip())
        s.add(item)
        s.flush()   # flush отправляет запись в базу заранее, чтобы получить её id
        return item.id

def get_item(item_id: int) -> Optional[MediaItem]:
    with session_scope() as s:
        return s.get(MediaItem, item_id)

def update_item(item_id: int, media_type: str, title: str, status: str, progress: int, total: Optional[int], rating: Optional[int], notes: str = "") -> None:
    _check_fields(media_type, title, status, progress, total, rating)
    with session_scope() as s:
        item = s.get(MediaItem, item_id)
        if item is None:
            raise ValueError("Запись не найдена (возможно, её уже удалили).")
        item.type = media_type
        item.title = title.strip()
        item.status = status
        item.progress = progress
        item.total = total
        item.rating = rating
        item.notes = notes.strip()

def increment_progress(item_id: int, step: int = 1) -> MediaItem:
    """
    Кнопка "+1": ещё одна серия/глава/страница.
    Если дошли до конца - запись сама становится "Завершено",
    если только начали - "В процессе".
    """
    with session_scope() as s:
        item = s.get(MediaItem, item_id)
        if item is None:
            raise ValueError("Запись не найдена.")
        item.progress += step
        if item.total is not None and item.progress >= item.total:
            item.progress = item.total
            item.status = "completed"
        elif item.status == "planned":
            item.status = "in progress"
        s.flush()
        return item

def delete_item(item_id: int) -> None:
    with session_scope() as s:
        item = s.get(MediaItem, item_id)
        if item is not None:
            s.delete(item)

def search_items(query: str = "", media_type: Optional[str] = None, status: Optional[str] = None, sort: str = "updated") -> list[MediaItem]:
    """Поиск по названию и заметкам. media_type / status = None означает "все"."""
    statement = select(MediaItem)
    text = query.strip()
    if text:
        pattern = f"%{text}%"   # % в LIKE означает "любые символы"
        statement = statement.where(or_(MediaItem.title.ilike(pattern), MediaItem.notes.ilike(pattern)))
    if media_type:
        statement = statement.where(MediaItem.type == media_type)
    if status:
        statement = statement.where(MediaItem.status == status)

    sort_options = {
        "updated": MediaItem.updated_at.desc(),
        "title": MediaItem.title.asc(),
        "rating": MediaItem.rating.desc(),
        "added": MediaItem.created_at.desc(),
    }
    order = sort_options.get(sort, MediaItem.updated_at.desc())

    with session_scope() as s:
        return list(s.scalars(statement.order_by(order, MediaItem.id.desc())).all())

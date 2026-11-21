"""Данные, которые создаются при самом первом запуске (всё можно поменять в программе)."""
from __future__ import annotations
from sqlalchemy import func, select
from .base import session_scope
from .models import SortRule

# Правила сортировки "из коробки": название, ключевые слова, расширения, папка, приоритет.
# Ключевые слова есть и на русском, и на английском - файлы называют по-разному.
DEFAULT_RULES = [
    ("Домашние задания", "домашка, дз, задание, homework, assignment, hw, lab", "",
     "Учёба/Домашние задания", 50),
    ("Лекции и конспекты", "лекция, конспект, урок, lecture, lesson, notes, syllabus", "",
     "Учёба/Лекции", 40),
    ("Экзамены", "экзамен, билеты, a-level, alevel, past paper, 9626, exam", "",
     "Учёба/Экзамены", 45),
    ("Чеки и счета", "чек, счёт, квитанция, оплата, invoice, receipt, payment, ticket", "",
     "Финансы", 30),
    ("Аниме и манга", "аниме, манга, глава, anime, manga, chapter", "",
     "Медиа/Аниме-манга", 20),
]

def add_default_data() -> None:
    """Добавляет стандартные правила, но только если таблица правил пустая."""
    with session_scope() as s:
        rules_count = s.scalar(select(func.count()).select_from(SortRule))
        if rules_count > 0:
            return   # пользователь уже работал с программой - ничего не трогаем
        for name, keywords, extensions, folder, priority in DEFAULT_RULES:
            s.add(SortRule(name=name, keywords=keywords, extensions=extensions,
                           target_folder=folder, priority=priority, enabled=True))


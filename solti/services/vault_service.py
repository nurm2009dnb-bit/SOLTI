"""Хранилище паролей.

Как устроена защита:
  * Пользователь придумывает МАСТЕР-ПАРОЛЬ. Он нигде не сохраняется.
  * Из него с помощью Scrypt и случайной "соли" получается ключ шифрования.
    Scrypt специально работает медленно и требует много памяти, поэтому
    подбирать пароль перебором очень дорого. Соль хранится в базе.
  * Каждый пароль шифруется алгоритмом Fernet (AES-128-CBC + HMAC-SHA256):
    его нельзя ни прочитать, ни незаметно подменить без ключа.
  * Чтобы проверить мастер-пароль, расшифровываем сохранённое контрольное
    значение. Не получилось - значит, пароль неверный.
  * Ключ живёт только в памяти, пока хранилище открыто; lock() его стирает.
"""
from __future__ import annotations
import base64    # Fernet требует ключ в виде base64-строки
import os        # os.urandom - криптографически стойкие случайные байты для соли
import secrets   # стойкий генератор случайных чисел для паролей (random для этого не годится)
import string    # готовые наборы символов: буквы, цифры
from typing import Optional

# cryptography - проверенная библиотека шифрования, свои алгоритмы писать нельзя
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import or_, select

from ..database.base import session_scope
from ..database.models import Credential, VaultMeta

_CHECK_TEXT = b"solti-vault-ok"   # контрольный текст: если расшифровался - мастер-пароль верный
MIN_MASTER_LENGTH = 6


class VaultLockedError(Exception):
    """Хранилище закрыто - сначала нужно ввести мастер-пароль."""


class WrongPasswordError(Exception):
    """Неверный мастер-пароль."""


def _derive_key(master: str, salt: bytes) -> bytes:
    """Получает 32-байтовый ключ из мастер-пароля и соли.

    n=2**15, r=8, p=1 - рекомендуемые параметры Scrypt: на обычном ПК около 0.1 с на попытку.
    """
    kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
    return base64.urlsafe_b64encode(kdf.derive(master.encode("utf-8")))


def generate_password(length: int = 16, symbols: bool = True) -> str:
    """Случайный пароль, в котором точно есть строчная, заглавная буква, цифра (и спецсимвол)."""
    length = max(8, min(length, 64))
    groups = [string.ascii_lowercase, string.ascii_uppercase, string.digits]
    if symbols:
        groups.append("!@#$%^&*()-_=+?")

    # по одному символу из каждой группы гарантированно, остальное - из всех сразу
    chars = [secrets.choice(group) for group in groups]
    all_chars = "".join(groups)
    chars += [secrets.choice(all_chars) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)   # перемешиваем, чтобы обязательные символы не стояли в начале
    return "".join(chars)


class Vault:
    def __init__(self) -> None:
        self._fernet: Optional[Fernet] = None   # объект шифрования; есть только когда хранилище открыто

    # ---- состояние -----------------------------------------------------
    @staticmethod
    def is_initialized() -> bool:
        """Создан ли уже мастер-пароль."""
        with session_scope() as s:
            return s.scalar(select(VaultMeta.id).limit(1)) is not None

    @property
    def is_unlocked(self) -> bool:
        return self._fernet is not None

    def _require_unlocked(self) -> Fernet:
        if self._fernet is None:
            raise VaultLockedError("Сначала откройте хранилище.")
        return self._fernet

    # ---- создание / открытие -------------------------------------------
    def setup(self, master: str) -> None:
        """Первый запуск: создаём мастер-пароль."""
        if self.is_initialized():
            raise ValueError("Мастер-пароль уже создан.")
        if len(master) < MIN_MASTER_LENGTH:
            raise ValueError(f"Мастер-пароль должен быть не короче {MIN_MASTER_LENGTH} символов.")
        salt = os.urandom(16)
        fernet = Fernet(_derive_key(master, salt))
        with session_scope() as s:
            s.add(VaultMeta(salt=salt, verifier=fernet.encrypt(_CHECK_TEXT)))
        self._fernet = fernet

    def unlock(self, master: str) -> None:
        with session_scope() as s:
            meta = s.scalar(select(VaultMeta).limit(1))
            if meta is None:
                raise ValueError("Хранилище ещё не создано.")
            salt, verifier = meta.salt, meta.verifier
        fernet = Fernet(_derive_key(master, salt))
        try:
            if fernet.decrypt(verifier) != _CHECK_TEXT:
                raise WrongPasswordError("Неверный мастер-пароль.")
        except InvalidToken:
            # Fernet не смог расшифровать - значит, ключ (то есть пароль) неверный
            raise WrongPasswordError("Неверный мастер-пароль.") from None
        self._fernet = fernet

    def lock(self) -> None:
        self._fernet = None

    # ---- записи ---------------------------------------------------------
    def add(self, site: str, username: str, password: str, notes: str = "") -> int:
        fernet = self._require_unlocked()
        if not site.strip():
            raise ValueError("Укажите сайт или сервис.")
        if not password:
            raise ValueError("Введите пароль.")
        with session_scope() as s:
            row = Credential(site=site.strip(), username=username.strip(),
                             encrypted_password=fernet.encrypt(password.encode("utf-8")),
                             notes=notes.strip())
            s.add(row)
            s.flush()
            return row.id

    def update(self, cred_id: int, site: str, username: str, password: str, notes: str = "") -> None:
        fernet = self._require_unlocked()
        if not site.strip():
            raise ValueError("Укажите сайт или сервис.")
        if not password:
            raise ValueError("Введите пароль.")
        with session_scope() as s:
            row = s.get(Credential, cred_id)
            if row is None:
                raise ValueError("Запись не найдена.")
            row.site = site.strip()
            row.username = username.strip()
            row.notes = notes.strip()
            row.encrypted_password = fernet.encrypt(password.encode("utf-8"))

    def delete(self, cred_id: int) -> None:
        self._require_unlocked()
        with session_scope() as s:
            row = s.get(Credential, cred_id)
            if row is not None:
                s.delete(row)

    def search(self, query: str = "") -> list[Credential]:
        """Поиск по сайту, логину и заметкам. Пароли в результате ВСЁ ЕЩЁ зашифрованы - см. reveal()."""
        self._require_unlocked()
        statement = select(Credential)
        text = query.strip()
        if text:
            pattern = f"%{text}%"
            statement = statement.where(or_(Credential.site.ilike(pattern),
                                            Credential.username.ilike(pattern),
                                            Credential.notes.ilike(pattern)))
        with session_scope() as s:
            return list(s.scalars(statement.order_by(Credential.site)).all())

    def reveal(self, cred_id: int) -> str:
        """Расшифровывает и возвращает пароль одной записи."""
        fernet = self._require_unlocked()
        with session_scope() as s:
            row = s.get(Credential, cred_id)
            if row is None:
                raise ValueError("Запись не найдена.")
            token = row.encrypted_password
        try:
            return fernet.decrypt(token).decode("utf-8")
        except InvalidToken:
            raise ValueError("Эту запись не удалось расшифровать.") from None

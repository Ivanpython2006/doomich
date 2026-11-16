"""Криптография и безопасность: пароли, токены, шифрование, коды, TOTP, лимиты."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
import unicodedata
import uuid
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from threading import Lock

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from doomich_api.config import get_settings

# Алфавит без похожих символов (0/O, 1/I/L)
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


# --------------------------------------------------------------------------- пароли
@lru_cache
def _hasher() -> PasswordHasher:
    s = get_settings()
    return PasswordHasher(
        time_cost=s.argon2_time_cost,
        memory_cost=s.argon2_memory_kib,
        parallelism=s.argon2_parallelism,
    )


def hash_secret(value: str) -> str:
    return _hasher().hash(value)


def verify_secret(stored_hash: str, value: str) -> bool:
    try:
        return _hasher().verify(stored_hash, value)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# Пустышка для выравнивания времени ответа, когда логина не существует
_DUMMY_HASH: str | None = None


def dummy_verify() -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_secret("dummy-password-for-timing")
    verify_secret(_DUMMY_HASH, "wrong-password")


def password_problems(password: str) -> list[str]:
    """Простая проверка стойкости (подробная — на клиенте)."""
    problems = []
    if len(password) < 10:
        problems.append("Пароль должен быть не короче 10 символов")
    if len(set(password)) < 5:
        problems.append("В пароле слишком мало разных символов")
    if password.lower() in {"1234567890", "qwertyuiop", "password12", "йцукенгшщз"}:
        problems.append("Слишком простой пароль")
    return problems


# --------------------------------------------------------------------------- токены
@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    university_id: uuid.UUID
    role: str


def create_access_token(user_id: uuid.UUID, university_id: uuid.UUID, role: str) -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "uni": str(university_id),
        "role": role,
        "typ": "access",
        "iat": now,
        "exp": now + s.access_token_ttl_s,
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_access_token(token: str) -> AccessClaims:
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret.get_secret_value(), algorithms=["HS256"])
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return AccessClaims(uuid.UUID(payload["sub"]), uuid.UUID(payload["uni"]), payload["role"])


def create_admin_token(admin_id: uuid.UUID, role: str, university_id: uuid.UUID | None) -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": str(admin_id),
        "role": role,
        "uni": str(university_id) if university_id else None,
        "typ": "admin",
        "iat": now,
        "exp": now + s.admin_token_ttl_s,
    }
    return jwt.encode(payload, s.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_admin_token(token: str) -> dict:
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret.get_secret_value(), algorithms=["HS256"])
    if payload.get("typ") != "admin":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_refresh_token() -> tuple[str, str]:
    """(токен для клиента, его хэш для БД)."""
    token = secrets.token_urlsafe(48)
    return token, sha256_hex(token)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def refresh_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=get_settings().refresh_token_ttl_s)


# --------------------------------------------------------------------------- шифрование
class Crypto:
    """Конвертное шифрование: у каждого пользователя свой ключ данных (DEK),
    зашифрованный мастер-ключом (KEK). Мастер-ключ хранится вне БД."""

    def __init__(self, master_key: bytes, key_version: int = 1) -> None:
        if len(master_key) != 32:
            raise ValueError("master key must be 32 bytes")
        self._kek = AESGCM(master_key)
        self.key_version = key_version
        self._dek_cache: OrderedDict[tuple[bytes, uuid.UUID], AESGCM] = OrderedDict()
        self._lock = Lock()

    def new_wrapped_dek(self, user_id: uuid.UUID) -> bytes:
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        return nonce + self._kek.encrypt(nonce, dek, b"dek:" + user_id.bytes)

    def _dek(self, wrapped: bytes, user_id: uuid.UUID) -> AESGCM:
        key = (wrapped, user_id)  # ключ кэша включает пользователя: иначе обходилась бы проверка AAD
        with self._lock:
            cached = self._dek_cache.get(key)
            if cached is not None:
                self._dek_cache.move_to_end(key)
                return cached
        raw = self._kek.decrypt(wrapped[:12], wrapped[12:], b"dek:" + user_id.bytes)
        aes = AESGCM(raw)
        with self._lock:
            self._dek_cache[key] = aes
            if len(self._dek_cache) > 5000:
                self._dek_cache.popitem(last=False)
        return aes

    def encrypt(self, wrapped_dek: bytes, user_id: uuid.UUID, data: bytes, purpose: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._dek(wrapped_dek, user_id).encrypt(nonce, data, purpose.encode())

    def decrypt(self, wrapped_dek: bytes, user_id: uuid.UUID, blob: bytes, purpose: str) -> bytes:
        return self._dek(wrapped_dek, user_id).decrypt(blob[:12], blob[12:], purpose.encode())

    def encrypt_text(self, wrapped_dek: bytes, user_id: uuid.UUID, text: str, purpose: str) -> bytes:
        return self.encrypt(wrapped_dek, user_id, text.encode(), purpose)

    def decrypt_text(self, wrapped_dek: bytes, user_id: uuid.UUID, blob: bytes, purpose: str) -> str:
        return self.decrypt(wrapped_dek, user_id, blob, purpose).decode()

    # Секреты сервиса (например, TOTP администраторов) шифруются мастер-ключом напрямую
    def seal(self, data: bytes, purpose: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._kek.encrypt(nonce, data, purpose.encode())

    def unseal(self, blob: bytes, purpose: str) -> bytes:
        return self._kek.decrypt(blob[:12], blob[12:], purpose.encode())

    def rewrap(self, wrapped: bytes, user_id: uuid.UUID, new: Crypto) -> bytes:
        """Перешифровать DEK новым мастер-ключом (ротация ключей)."""
        raw = self._kek.decrypt(wrapped[:12], wrapped[12:], b"dek:" + user_id.bytes)
        nonce = os.urandom(12)
        return nonce + new._kek.encrypt(nonce, raw, b"dek:" + user_id.bytes)


@lru_cache
def get_crypto() -> Crypto:
    return Crypto(get_settings().master_key_bytes)


# --------------------------------------------------------------------------- коды
def random_code(length: int) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def format_groups(code: str, size: int = 4) -> str:
    return "-".join(code[i : i + size] for i in range(0, len(code), size))


def normalize_code(code: str) -> str:
    """Убрать дефисы и пробелы, привести к верхнему регистру.

    Похожих символов (0/O, 1/I/L) в алфавите нет, поэтому опечатки в них не исправляем —
    такой код просто не найдётся.
    """
    return "".join(ch for ch in code.upper() if ch.isalnum())


def new_invite_code() -> str:
    return format_groups(random_code(8))


def invite_code_hash(code: str) -> str:
    pepper = get_settings().invite_pepper.get_secret_value().encode()
    return hmac.new(pepper, normalize_code(code).encode(), hashlib.sha256).hexdigest()


def new_recovery_code() -> str:
    """20 символов ≈ 98 бит энтропии."""
    return format_groups(random_code(20))


def normalize_login(login: str) -> str:
    return unicodedata.normalize("NFKC", login).strip().casefold()


# --------------------------------------------------------------------------- псевдонимы
_ADJ_RU = [
    "Тихий",
    "Быстрый",
    "Мудрый",
    "Смелый",
    "Ясный",
    "Добрый",
    "Звёздный",
    "Северный",
    "Весёлый",
    "Хитрый",
    "Ловкий",
    "Яркий",
    "Спокойный",
    "Ночной",
    "Солнечный",
    "Лесной",
]
_NOUN_RU = [
    "Енот",
    "Филин",
    "Лис",
    "Кит",
    "Ёж",
    "Барсук",
    "Сокол",
    "Бобёр",
    "Тюлень",
    "Пингвин",
    "Дельфин",
    "Волк",
    "Кот",
    "Ворон",
    "Лось",
    "Хомяк",
]
_ADJ_EN = ["Quiet", "Swift", "Wise", "Brave", "Clever", "Bright", "Calm", "Lucky", "Sunny", "Northern"]
_NOUN_EN = ["Raccoon", "Owl", "Fox", "Whale", "Hedgehog", "Falcon", "Beaver", "Penguin", "Wolf", "Otter"]


def suggest_pseudonyms(locale: str = "ru", count: int = 5) -> list[str]:
    adjs, nouns = (_ADJ_RU, _NOUN_RU) if locale.startswith("ru") else (_ADJ_EN, _NOUN_EN)
    return [f"{secrets.choice(adjs)}{secrets.choice(nouns)}{secrets.randbelow(90) + 10}" for _ in range(count)]


_COMMON_FIRST_NAMES = {
    "александр",
    "алексей",
    "андрей",
    "анна",
    "анастасия",
    "артём",
    "артем",
    "борис",
    "вадим",
    "валерия",
    "василий",
    "виктор",
    "виктория",
    "владимир",
    "дарья",
    "денис",
    "дмитрий",
    "евгений",
    "екатерина",
    "елена",
    "иван",
    "игорь",
    "илья",
    "ирина",
    "кирилл",
    "ксения",
    "максим",
    "мария",
    "михаил",
    "наталья",
    "никита",
    "николай",
    "олег",
    "ольга",
    "павел",
    "полина",
    "роман",
    "сергей",
    "софия",
    "татьяна",
    "юлия",
    "ярослав",
    "alexander",
    "ivan",
    "maria",
    "anna",
    "dmitry",
    "sergey",
}
_SURNAME_SUFFIXES = ("ов", "ев", "ёв", "ин", "ын", "ова", "ева", "ина", "ский", "ская", "енко", "ук", "юк")


def looks_like_real_name(login: str) -> bool:
    """Эвристика: похоже ли на ФИО. Не блокирует, а лишь предупреждает пользователя."""
    parts = [p for p in "".join(ch if ch.isalpha() else " " for ch in login.lower()).split() if p]
    if any(p in _COMMON_FIRST_NAMES for p in parts):
        return True
    return any(len(p) >= 5 and p.endswith(_SURNAME_SUFFIXES) for p in parts) and len(parts) >= 2


# --------------------------------------------------------------------------- TOTP
def new_totp_secret() -> str:
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


def totp_uri(secret: str, login: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=login, issuer_name="Doomich Admin")


# --------------------------------------------------------------------------- лимиты
class RateLimiter:
    """Скользящее окно в памяти процесса. Ключи (например, IP) не пишутся в логи и на диск.

    Для нескольких экземпляров API используйте лимиты в Nginx/Valkey; этот лимитер —
    второй рубеж внутри процесса.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > window_s:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            if len(self._hits) > 100_000:  # защита памяти
                self._hits.clear()
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()

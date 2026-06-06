"""
Подключение к двум базам данных через SQLAlchemy 2.0.

У нас две физически разных SQLite-БД:
  1. bkrs.db    — словарь, read-only, ~1.2 ГБ
  2. users.db   — профили пользователей, списки слов, прогресс

Для каждой создаём свою Engine и свою фабрику сессий. У моделей будет
два разных базовых класса (DictionaryBase, UsersBase), чтобы не путать
таблицы между БД.

В эндпоинтах через Depends() запрашиваем нужный тип сессии:
    def endpoint(db: Session = Depends(get_dictionary_db)):
        ...
    def endpoint(db: Session = Depends(get_users_db)):
        ...
"""
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from api.config import settings


# ============================================================================
# PRAGMA для всех SQLite-соединений
# ============================================================================

@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Включаем foreign keys для каждого нового соединения SQLite.
    По умолчанию они выключены — это историческая особенность SQLite.
    Без этого не работает ON DELETE CASCADE.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


# ============================================================================
# Engine #1: словарь БКРС (read-only)
# ============================================================================

dictionary_engine = create_engine(
    settings.DICTIONARY_DB_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

DictionarySessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=dictionary_engine,
)


class DictionaryBase(DeclarativeBase):
    """Базовый класс для моделей таблиц словаря (words, meanings, examples...)."""
    pass


def get_dictionary_db() -> Generator[Session, None, None]:
    """FastAPI dependency: сессия словарной БД (read-only режим)."""
    from sqlalchemy import text
    db = DictionarySessionLocal()
    try:
        # query_only режим — защита от случайных изменений словаря
        db.execute(text("PRAGMA query_only=ON"))
        yield db
    finally:
        db.close()


# ============================================================================
# Engine #2: пользовательские данные
# ============================================================================

users_engine = create_engine(
    settings.USERS_DB_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

UsersSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=users_engine,
)


class UsersBase(DeclarativeBase):
    """Базовый класс для моделей пользовательских данных."""
    pass


def get_users_db() -> Generator[Session, None, None]:
    """FastAPI dependency: сессия БД пользовательских данных (read-write)."""
    db = UsersSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# Совместимость со старым кодом
# ============================================================================
# Старый код использовал get_db, ссылающийся на словарь. Оставляем алиас,
# чтобы не ломать существующие импорты в роутерах.
get_db = get_dictionary_db
Base = DictionaryBase
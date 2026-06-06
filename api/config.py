"""
Настройки приложения.

Используем pydantic-settings — это промышленный стандарт для конфигурации
FastAPI-приложений. Принципы:
  - Все настройки в одном месте (Single Source of Truth).
  - Чувствительные данные (пути, ключи API) можно переопределить через .env
    или переменные окружения, не меняя код.
  - Валидация типов "бесплатно" — Pydantic проверит, что DATABASE_URL — строка,
    а PORT — число.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# Корень backend-проекта (на два уровня выше: api/config.py → api/ → backend/)
BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Настройки приложения. Можно переопределить через .env или env vars."""

    # === Сервер ===
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # === База данных словаря (read-only, словарь БКРС) ===
    DICTIONARY_DB_URL: str = f"sqlite:///{BACKEND_ROOT / 'data' / 'bkrs.db'}"

    # === База данных пользователей (read-write) ===
    # Отдельная БД для пользовательских данных: профили, списки слов, прогресс.
    # Разделение нужно потому, что словарь читается в режиме query_only, а
    # пользовательские данные постоянно меняются. Также удобно: словарь можно
    # перевыкладывать целиком (например, при обновлении БКРС), не теряя
    # пользовательских данных.
    USERS_DB_URL: str = f"sqlite:///{BACKEND_ROOT / 'data' / 'users.db'}"

    # === API ===
    API_PREFIX: str = "/api"
    API_TITLE: str = "Chinese Dictionary API"
    API_VERSION: str = "0.1.0"

    # === CORS ===
    CORS_ORIGINS: list[str] = ["*"]

    # === Лимиты поиска ===
    SEARCH_DEFAULT_LIMIT: int = 20
    SEARCH_MAX_LIMIT: int = 100

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
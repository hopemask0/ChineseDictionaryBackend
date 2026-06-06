"""
Точка входа FastAPI-приложения.

Запуск:
    # Из корня backend/:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

После запуска:
  - http://localhost:8000/docs     — интерактивная документация Swagger UI
  - http://localhost:8000/redoc    — альтернативная документация ReDoc
  - http://localhost:8000/api/health — проверка работоспособности
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import settings
from api.db_init import init_users_database
from api.routers import auth, characters, health, leveltest, lists, progress, search, words


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan — современный способ управления "стартом и остановкой" приложения.

    Перед yield — то, что выполняется при запуске.
    После yield — при graceful shutdown.
    """
    # При первом запуске создаём users.db и таблицы пользователей.
    # Если БД уже есть — ничего не делает.
    init_users_database()

    print("=" * 60)
    print(f"🚀 Starting {settings.API_TITLE} v{settings.API_VERSION}")
    print(f"   Dictionary DB: {settings.DICTIONARY_DB_URL}")
    print(f"   Users DB:      {settings.USERS_DB_URL}")
    print(f"   Docs:          http://{settings.HOST}:{settings.PORT}/docs")
    print("=" * 60)
    yield
    print("👋 Shutting down")


# Создаём приложение FastAPI
app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=(
        "REST API для мобильного приложения-словаря китайского языка. "
        "Источник данных: БКРС (Большой китайско-русский словарь)."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# === Middleware ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Подключаем роутеры ===
app.include_router(health.router, prefix=settings.API_PREFIX)
app.include_router(search.router, prefix=settings.API_PREFIX)
app.include_router(words.router, prefix=settings.API_PREFIX)
app.include_router(auth.router, prefix=settings.API_PREFIX)
app.include_router(characters.router, prefix=settings.API_PREFIX)
app.include_router(lists.router, prefix=settings.API_PREFIX)
app.include_router(progress.router, prefix=settings.API_PREFIX)
app.include_router(leveltest.router, prefix=settings.API_PREFIX)


@app.get("/", include_in_schema=False)
def root():
    """Корневой эндпоинт — просто перенаправляем на документацию."""
    return {
        "message": "Chinese Dictionary API is running",
        "docs": "/docs",
        "health": f"{settings.API_PREFIX}/health",
    }
"""
Health check — проверка, что сервер живой и БД доступна.

Используется:
  - Для мониторинга в продакшне (Kubernetes, Docker)
  - Для быстрой диагностики из браузера: открыл /api/health → видишь, всё ОК
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Word
from api.schemas import HealthResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Проверка работоспособности",
    description="Возвращает статус сервиса и количество слов в БД.",
)
def health_check(db: Session = Depends(get_db)) -> HealthResponse:
    """
    Запрашиваем COUNT(*) из words как минимальный smoke-test:
    подключение к БД работает, таблицы на месте, данные есть.
    """
    try:
        word_count = db.execute(select(func.count()).select_from(Word)).scalar() or 0
        return HealthResponse(
            status="ok",
            database="connected",
            word_count=word_count,
        )
    except Exception as e:
        # 503 Service Unavailable — стандартный код для "сервер жив, но
        # критичная зависимость недоступна"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database is unavailable: {e}",
        )

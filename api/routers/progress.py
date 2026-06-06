"""
Эндпоинты тренажёра и прогресса:

  POST /api/progress/review         — записать ответ пользователя
  GET  /api/progress/session/{id}   — подготовить карточки для тренировки
  GET  /api/progress/stats          — сводная статистика
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.database import get_dictionary_db, get_users_db
from api.dependencies import get_current_user
from api.models_users import User
from api.schemas import (
    ProgressItem, ProgressStats, ReviewAnswer, TrainerSession,
)
from api.services import progress_service

router = APIRouter(prefix="/progress", tags=["Progress"])


@router.post(
    "/review",
    response_model=ProgressItem,
    summary="Записать ответ пользователя на слово",
    description=(
        "Вызывается во время тренировки на каждый ответ. "
        "knows=true → пользователь нажал 'Знаю'. "
        "knows=false → пользователь нажал 'Учу'. "
        "Сервер обновляет статистику и возвращает обновлённый прогресс."
    ),
)
def record_review(
    payload: ReviewAnswer,
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
) -> ProgressItem:
    data = progress_service.record_answer(
        users_db=users_db,
        user_id=current_user.id,
        word_id=payload.word_id,
        knows=payload.knows,
    )
    return ProgressItem(**data)


@router.get(
    "/session/{list_id}",
    response_model=TrainerSession,
    summary="Подготовить карточки для тренировки",
    description=(
        "Возвращает все слова списка вместе с их текущим прогрессом, "
        "готовые для отображения как карточки в тренажёре."
    ),
    responses={404: {"description": "Список не найден"}},
)
def prepare_training_session(
    list_id: int,
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
    dict_db: Session = Depends(get_dictionary_db),
) -> TrainerSession:
    try:
        data = progress_service.prepare_session(
            users_db=users_db, dict_db=dict_db,
            user_id=current_user.id, list_id=list_id,
        )
    except progress_service.ListNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
    return TrainerSession(**data)


@router.get(
    "/stats",
    response_model=ProgressStats,
    summary="Общая статистика прогресса пользователя",
)
def get_stats(
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
) -> ProgressStats:
    data = progress_service.get_user_stats(users_db, current_user.id)
    return ProgressStats(**data)

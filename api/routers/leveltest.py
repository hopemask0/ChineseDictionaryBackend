"""
Эндпоинты входного HSK-теста:

  GET  /api/leveltest/questions?hsk_level=N — получить пакет из 10 вопросов
  POST /api/leveltest/result                — сохранить определённый уровень
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.database import get_dictionary_db, get_users_db
from api.dependencies import get_current_user
from api.models_users import User
from api.schemas import (
    LevelTestResultRequest, LevelTestResultResponse,
    TestQuestion, TestQuestionBatch,
)
from api.services import leveltest_service

router = APIRouter(prefix="/leveltest", tags=["Level Test"])


@router.get(
    "/questions",
    response_model=TestQuestionBatch,
    summary="Получить пакет вопросов для HSK уровня",
    description=(
        "Возвращает 10 вопросов трёх типов (multiple-choice перевод, "
        "multiple-choice иероглиф, ввод текста) для указанного HSK уровня. "
        "Дистракторы — случайные слова того же уровня."
    ),
)
def get_questions(
    hsk_level: int = Query(..., ge=1, le=6, description="HSK уровень 1-6"),
    count: int = Query(10, ge=5, le=20),
    dict_db: Session = Depends(get_dictionary_db),
) -> TestQuestionBatch:
    try:
        data = leveltest_service.get_questions(
            dict_db=dict_db, hsk_level=hsk_level, count=count,
        )
    except leveltest_service.NotEnoughWordsError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    return TestQuestionBatch(
        hsk_level=data["hsk_level"],
        questions=[TestQuestion(**q) for q in data["questions"]],
    )


@router.post(
    "/result",
    response_model=LevelTestResultResponse,
    summary="Сохранить результат теста",
    description=(
        "Принимает финальный HSK-уровень и статистику ответов. "
        "Обновляет поле level в профиле пользователя (по маппингу HSK→app)."
    ),
)
def save_result(
    payload: LevelTestResultRequest,
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
) -> LevelTestResultResponse:
    app_level = leveltest_service.save_level(
        users_db=users_db,
        user_id=current_user.id,
        hsk_level=payload.determined_level,
    )
    return LevelTestResultResponse(
        determined_hsk_level=payload.determined_level,
        app_level=app_level,
        saved=True,
    )

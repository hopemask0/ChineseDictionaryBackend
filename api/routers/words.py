"""
Эндпоинты для работы со словами:
  - GET /api/words/random — случайное слово (для "Слова дня")
  - GET /api/words/{id}   — полная карточка слова

ВАЖНО про порядок объявления:
  /random ОБЯЗАТЕЛЬНО должен идти перед /{word_id}. FastAPI сопоставляет
  пути сверху вниз — если /{word_id} объявлен первым, то запрос на /random
  попадёт в него и упадёт с 422 (т.к. "random" не число).
"""
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Word
from api.schemas import WordDetail
from api.services import word_service

router = APIRouter(tags=["Words"])


@router.get(
    "/words/random",
    response_model=WordDetail,
    summary="Случайное слово (для главного экрана)",
    description=(
        "Возвращает случайное слово под фильтры. Используется на главном "
        "экране для блока 'Слово дня'.\n\n"
        "Алгоритм: случайный id в диапазоне → ближайшее подходящее слово. "
        "Работает за миллисекунды даже на 3.4 млн слов в БД."
    ),
    responses={
        404: {"description": "Не нашлось ни одного слова под фильтры"},
    },
)
def get_random_word(
    min_chars: int = Query(1, ge=1, le=10, description="Минимум иероглифов"),
    max_chars: int = Query(3, ge=1, le=10, description="Максимум иероглифов"),
    hsk_level: int | None = Query(None, ge=1, le=6, description="Уровень HSK 1-6"),
    db: Session = Depends(get_db),
) -> WordDetail:
    """
    Параметры по умолчанию (1-3 иероглифа, common-категория с пиньинь) дают
    хорошее "слово дня" — короткое, понятное, обычная лексика.
    """
    try:
        word = word_service.get_random_word(
            db=db,
            min_char_length=min_chars,
            max_char_length=max_chars,
            hsk_level=hsk_level,
        )
    except word_service.NoWordsFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return WordDetail.model_validate(word)


@router.get(
    "/words/{word_id}",
    response_model=WordDetail,
    summary="Получить полную информацию о слове",
    description=(
        "Возвращает все значения слова, примеры использования, "
        "грамматические пометы и перекрёстные ссылки."
    ),
    responses={
        404: {"description": "Слово с таким ID не найдено"},
    },
)
def get_word_detail(
    word_id: int = Path(
        ..., gt=0, description="ID слова, полученный из /api/search"
    ),
    db: Session = Depends(get_db),
) -> WordDetail:
    word = db.execute(
        select(Word).where(Word.id == word_id)
    ).scalar_one_or_none()

    if word is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Word with id {word_id} not found",
        )

    return WordDetail.model_validate(word)

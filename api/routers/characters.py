"""
Эндпоинты для данных иероглифов (Make Me a Hanzi):
  - GET /api/characters/{ch}            — этимология, декомпозиция, радикал
  - GET /api/characters/{ch}/strokes    — SVG-данные для анимации написания
  - GET /api/words/{word_id}/characters — все иероглифы из слова с этимологией

Источник данных: github.com/skishore/makemeahanzi (CC-BY 4.0)
"""
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Word
from api.schemas import CharacterInfo, CharacterStrokes
from api.services import character_service

router = APIRouter(tags=["Characters"])


@router.get(
    "/characters/{ch}",
    response_model=CharacterInfo,
    summary="Этимология и структура иероглифа",
    description=(
        "Возвращает информацию об иероглифе: декомпозицию, радикал, "
        "тип этимологии (пиктографический, идеографический, фоносемантический) "
        "и текстовое описание происхождения.\n\n"
        "Источник: Make Me a Hanzi (~9000 наиболее употребительных иероглифов)."
    ),
    responses={
        404: {"description": "Иероглиф не покрыт базой Make Me a Hanzi"},
    },
)
def get_character_info(
    ch: str = Path(..., min_length=1, max_length=2, description="Иероглиф"),
    db: Session = Depends(get_db),
) -> CharacterInfo:
    try:
        data = character_service.get_character(db, ch)
    except character_service.CharacterNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Character '{ch}' not found in database",
        )
    return CharacterInfo(**data)


@router.get(
    "/characters/{ch}/strokes",
    response_model=CharacterStrokes,
    summary="Данные для анимации написания иероглифа",
    description=(
        "Возвращает SVG path-данные для каждой черты и координаты центральных "
        "линий, по которым клиент (hanzi-writer.js в WebView) рисует анимацию."
    ),
    responses={
        404: {"description": "Данных штрихов для этого иероглифа нет"},
    },
)
def get_character_strokes_endpoint(
    ch: str = Path(..., min_length=1, max_length=2, description="Иероглиф"),
    db: Session = Depends(get_db),
) -> CharacterStrokes:
    try:
        data = character_service.get_character_strokes(db, ch)
    except character_service.CharacterNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Strokes for '{ch}' not found",
        )
    return CharacterStrokes(**data)


@router.get(
    "/words/{word_id}/characters",
    response_model=list[CharacterInfo],
    summary="Этимология всех иероглифов слова",
    description=(
        "Для составного слова (например, 学习) возвращает информацию о каждом "
        "иероглифе по отдельности. Используется для блока 'Структура' на "
        "карточке слова.\n\n"
        "Иероглифы, не покрытые Make Me a Hanzi, пропускаются (не вызывают ошибку)."
    ),
    responses={
        404: {"description": "Слово с таким ID не найдено"},
    },
)
def get_word_characters(
    word_id: int = Path(..., gt=0, description="ID слова из /api/search"),
    db: Session = Depends(get_db),
) -> list[CharacterInfo]:
    word = db.execute(select(Word).where(Word.id == word_id)).scalar_one_or_none()
    if word is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Word with id {word_id} not found",
        )

    characters_data = character_service.get_characters_in_word(db, word.headword)
    return [CharacterInfo(**d) for d in characters_data]

"""
Эндпоинт поиска: GET /api/search

Принимает поисковый запрос и параметры пагинации/фильтрации,
возвращает список краткой информации о найденных словах.
"""
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.config import settings
from api.database import get_db
from api.schemas import SearchResponse, SearchResultItem
from api.services import search_service

router = APIRouter(tags=["Search"])


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Мультимодальный поиск слов",
    description=(
        "Ищет слова по иероглифу, пиньинь (с тонами или без) или русскому "
        "переводу. Тип запроса определяется автоматически по символам. "
        "Поддерживает префиксный поиск через звёздочку: 'xue*'."
    ),
)
def search(
    db: Annotated[Session, Depends(get_db)],
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=100,
            description="Поисковый запрос: иероглиф, пиньинь или перевод",
            examples=["学习", "xuexi", "учиться"],
        ),
    ],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=settings.SEARCH_MAX_LIMIT,
            description="Количество результатов на страницу (1-100)",
        ),
    ] = settings.SEARCH_DEFAULT_LIMIT,
    offset: Annotated[
        int,
        Query(ge=0, description="Смещение от начала выдачи"),
    ] = 0,
    category: Annotated[
        Optional[str],
        Query(
            description="Фильтр по категории слова",
            pattern="^(common|term|proper_noun|rare)$",
        ),
    ] = None,
    hsk_level: Annotated[
        Optional[int],
        Query(ge=1, le=6, description="Фильтр по уровню HSK 1-6"),
    ] = None,
) -> SearchResponse:
    """
    Параметры query string валидируются автоматически через Annotated[Query]:
    если limit > 100 или категория невалидна — FastAPI вернёт 422 без захода
    в наш код.
    """
    result = search_service.search_words(
        db=db,
        query=q,
        limit=limit,
        offset=offset,
        category=category,
        hsk_level=hsk_level,
    )

    return SearchResponse(
        query=q,
        total=result.total,
        limit=limit,
        offset=offset,
        items=[
            SearchResultItem(
                id=item.id,
                headword=item.headword,
                pinyin=item.pinyin,
                short_translation=item.short_translation,
                category=item.category,
                hsk_level=item.hsk_level,
            )
            for item in result.items
        ],
        elapsed_ms=round(result.elapsed_ms, 2),
    )

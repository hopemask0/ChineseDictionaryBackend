"""
Эндпоинты для системы списков слов.

Структура URL:
  /api/lists/catalog              GET    — каталог системных шаблонов
  /api/lists/my                   GET    — мои списки
  /api/lists/my                   POST   — создать пустой список
  /api/lists/subscribe            POST   — создать список из шаблона
  /api/lists/my/{id}              GET    — детали списка с содержимым
  /api/lists/my/{id}              PATCH  — переименовать список
  /api/lists/my/{id}              DELETE — удалить список
  /api/lists/my/{id}/items        POST   — добавить слово в список
  /api/lists/my/{id}/items/{wid}  DELETE — удалить слово из списка
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.database import get_dictionary_db, get_users_db
from api.dependencies import get_current_user
from api.models_users import User
from api.schemas import (
    AddWordToListRequest, UserListCreate, UserListDetail, UserListRead,
    UserListSubscribe, UserListUpdate, WordListTemplateRead,
)
from api.services import list_service

router = APIRouter(prefix="/lists", tags=["Lists"])


# ===== Каталог =====

@router.get(
    "/catalog",
    response_model=list[WordListTemplateRead],
    summary="Каталог системных списков",
    description=(
        "Возвращает каталог тематических списков, готовых к подписке. "
        "Например, 'Для путешествий', 'Бизнес-лексика'. "
        "Пользователь может подписаться на любой через POST /lists/subscribe — "
        "это создаст редактируемую копию в его списках."
    ),
)
def get_catalog(
    users_db: Session = Depends(get_users_db),
) -> list[WordListTemplateRead]:
    items = list_service.get_catalog(users_db)
    return [WordListTemplateRead(**item) for item in items]


# ===== Мои списки =====

@router.get(
    "/my",
    response_model=list[UserListRead],
    summary="Мои списки",
    description="Все списки текущего пользователя, новые сверху.",
)
def get_my_lists(
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
) -> list[UserListRead]:
    items = list_service.get_user_lists(users_db, current_user.id)
    return [UserListRead(**item) for item in items]


@router.post(
    "/my",
    response_model=UserListRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать пустой список",
)
def create_list(
    payload: UserListCreate,
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
) -> UserListRead:
    user_list = list_service.create_empty_list(
        users_db=users_db,
        user_id=current_user.id,
        title=payload.title,
        icon=payload.icon,
    )
    # Сразу подгружаем итоговое представление
    items = list_service.get_user_lists(users_db, current_user.id)
    item = next((i for i in items if i["id"] == user_list.id), None)
    return UserListRead(**item) if item else UserListRead(
        id=user_list.id,
        title=user_list.title,
        icon=user_list.icon,
        word_count=0,
        source_template_id=None,
        source_template_slug=None,
        created_at=user_list.created_at.isoformat(),
    )


@router.post(
    "/subscribe",
    response_model=UserListRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать список из системного шаблона",
    description=(
        "Копирует слова системного шаблона в новый пользовательский список. "
        "После создания список можно редактировать (добавлять/удалять слова)."
    ),
    responses={
        404: {"description": "Шаблон с таким ID не найден в каталоге"},
    },
)
def subscribe(
    payload: UserListSubscribe,
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
) -> UserListRead:
    try:
        user_list = list_service.subscribe_to_template(
            users_db=users_db,
            user_id=current_user.id,
            template_id=payload.template_id,
            custom_title=payload.custom_title,
        )
    except list_service.TemplateNotFoundError as e:
        raise HTTPException(404, str(e))

    items = list_service.get_user_lists(users_db, current_user.id)
    item = next((i for i in items if i["id"] == user_list.id), None)
    return UserListRead(**item)


@router.get(
    "/my/{list_id}",
    response_model=UserListDetail,
    summary="Содержимое списка",
    responses={404: {"description": "Список не найден"}},
)
def get_list_detail(
    list_id: int,
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
    dict_db: Session = Depends(get_dictionary_db),
) -> UserListDetail:
    try:
        return UserListDetail(**list_service.get_user_list_detail(
            users_db=users_db, dict_db=dict_db,
            user_id=current_user.id, list_id=list_id,
        ))
    except list_service.ListNotFoundError as e:
        raise HTTPException(404, str(e))


@router.patch(
    "/my/{list_id}",
    response_model=UserListRead,
    summary="Переименовать список или сменить иконку",
)
def update_list(
    list_id: int,
    payload: UserListUpdate,
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
) -> UserListRead:
    try:
        list_service.update_list(
            users_db=users_db, user_id=current_user.id, list_id=list_id,
            title=payload.title, icon=payload.icon,
        )
    except list_service.ListNotFoundError as e:
        raise HTTPException(404, str(e))

    items = list_service.get_user_lists(users_db, current_user.id)
    item = next((i for i in items if i["id"] == list_id), None)
    return UserListRead(**item)


@router.delete(
    "/my/{list_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить список",
)
def delete_list(
    list_id: int,
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
) -> None:
    try:
        list_service.delete_list(users_db, current_user.id, list_id)
    except list_service.ListNotFoundError as e:
        raise HTTPException(404, str(e))


# ===== Слова в списке =====

@router.post(
    "/my/{list_id}/items",
    status_code=status.HTTP_201_CREATED,
    summary="Добавить слово в список",
    responses={
        404: {"description": "Список или слово не найдены"},
        409: {"description": "Слово уже есть в этом списке"},
    },
)
def add_word(
    list_id: int,
    payload: AddWordToListRequest,
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
    dict_db: Session = Depends(get_dictionary_db),
) -> dict:
    try:
        list_service.add_word_to_list(
            users_db=users_db, dict_db=dict_db,
            user_id=current_user.id, list_id=list_id, word_id=payload.word_id,
        )
    except list_service.ListNotFoundError as e:
        raise HTTPException(404, str(e))
    except list_service.WordNotInDictionaryError as e:
        raise HTTPException(404, str(e))
    except list_service.WordAlreadyInListError as e:
        raise HTTPException(409, str(e))
    return {"status": "ok"}


@router.delete(
    "/my/{list_id}/items/{word_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить слово из списка",
)
def remove_word(
    list_id: int,
    word_id: int,
    current_user: User = Depends(get_current_user),
    users_db: Session = Depends(get_users_db),
) -> None:
    try:
        list_service.remove_word_from_list(
            users_db=users_db,
            user_id=current_user.id, list_id=list_id, word_id=word_id,
        )
    except list_service.ListNotFoundError as e:
        raise HTTPException(404, str(e))

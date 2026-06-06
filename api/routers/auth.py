"""
Эндпоинты авторизации: регистрация, логин, "кто я".

Упрощённая модель MVP:
  - При регистрации возвращаем user_id, клиент его сохраняет локально.
  - При запросах клиент передаёт user_id в заголовке X-User-Id.
  - Сервер находит пользователя по этому заголовку через зависимость
    current_user() (см. api/dependencies.py).

ВАЖНО: это НЕ безопасно для продакшна — любой может прислать любой user_id.
Для дипломного MVP допустимо. В развитии — добавить JWT/токены.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api.database import get_users_db
from api.dependencies import get_current_user
from api.models_users import User
from api.schemas import (
    AuthResponse,
    UserLogin,
    UserRead,
    UserRegister,
)
from api.services import user_service

router = APIRouter(tags=["Auth"])


@router.post(
    "/auth/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Зарегистрировать нового пользователя",
    description=(
        "Создаёт нового пользователя по username (уникальный) + display_name. "
        "Возвращает user_id, который клиент должен сохранить и передавать "
        "в заголовке X-User-Id при последующих запросах."
    ),
    responses={
        409: {"description": "Username уже занят"},
    },
)
def register(
    payload: UserRegister,
    db: Session = Depends(get_users_db),
) -> AuthResponse:
    try:
        user = user_service.register_user(
            db=db,
            username=payload.username,
            display_name=payload.display_name,
            level=payload.level,
            goals=payload.goals,
        )
    except user_service.UserAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    return AuthResponse(
        user_id=user.id,
        user=UserRead(**user_service.user_to_dict(user)),
    )


@router.post(
    "/auth/login",
    response_model=AuthResponse,
    summary="Войти по username",
    description="Возвращает user_id и профиль, если пользователь существует.",
    responses={
        404: {"description": "Пользователь не найден"},
    },
)
def login(
    payload: UserLogin,
    db: Session = Depends(get_users_db),
) -> AuthResponse:
    try:
        user = user_service.login_user(db=db, username=payload.username)
    except user_service.UserNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    return AuthResponse(
        user_id=user.id,
        user=UserRead(**user_service.user_to_dict(user)),
    )


@router.get(
    "/auth/me",
    response_model=UserRead,
    summary="Получить профиль текущего пользователя",
    description=(
        "Возвращает данные пользователя, идентифицированного по заголовку "
        "X-User-Id. Используется приложением при старте для проверки, "
        "что сохранённый user_id ещё валиден."
    ),
    responses={
        401: {"description": "Заголовок X-User-Id не передан"},
        404: {"description": "Пользователь с таким id не найден"},
    },
)
def get_me(
    current_user: User = Depends(get_current_user),
) -> UserRead:
    return UserRead(**user_service.user_to_dict(current_user))

"""
Общие FastAPI-зависимости.

Зависимости (dependencies) — это функции, которые FastAPI автоматически
вызывает перед эндпоинтом и подставляет их результат в параметры. Это
основной паттерн переиспользования кода в FastAPI:
  - получение сессии БД
  - проверка авторизации
  - валидация общих параметров
"""
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from api.database import get_users_db
from api.models_users import User
from api.services import user_service


def get_current_user(
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_users_db),
) -> User:
    """
    Извлекает текущего пользователя из заголовка X-User-Id.

    Использование в эндпоинте:
        @router.get("/some-endpoint")
        def my_endpoint(user: User = Depends(get_current_user)):
            # тут user.id = 42, и можем работать с его данными
            ...

    ⚠️ ВАЖНО для дипломного MVP:
    Это упрощённая авторизация — любой клиент может передать любой user_id
    и притвориться кем угодно. Для дипломного проекта допустимо как MVP.
    В развитии будем заменять на проверку JWT-токена с подписью.

    Бросает 401, если заголовок не передан.
    Бросает 404, если пользователь с таким id не найден.
    """
    if x_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-Id header is required",
        )

    try:
        return user_service.get_user_by_id(db=db, user_id=x_user_id)
    except user_service.UserNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User id={x_user_id} not found",
        )


def get_optional_user(
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_users_db),
) -> User | None:
    """
    Опциональная версия get_current_user.

    Возвращает None, если заголовок не передан или пользователь не найден.
    Не бросает исключений.

    Используется для эндпоинтов, которые работают и для гостей, и для
    зарегистрированных пользователей (например, поиск). Если пользователь
    залогинен — можем сохранять историю поиска, иначе — просто отдаём
    результаты.
    """
    if x_user_id is None:
        return None
    try:
        return user_service.get_user_by_id(db=db, user_id=x_user_id)
    except user_service.UserNotFoundError:
        return None

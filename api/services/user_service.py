"""
Бизнес-логика управления пользователями.

Отделение от router'ов даёт:
  - Логику можно вызывать не только из HTTP, но и из CLI/тестов
  - Эндпоинт остаётся тонким: валидация → service → ответ
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models_users import User, UserGoal, VALID_GOALS


class UserAlreadyExistsError(Exception):
    """Пользователь с таким username уже зарегистрирован."""
    pass


class UserNotFoundError(Exception):
    """Пользователь не найден."""
    pass


class InvalidGoalError(Exception):
    """Указана несуществующая цель."""
    pass


def register_user(
    db: Session,
    username: str,
    display_name: str,
    level: int | None,
    goals: list[str],
) -> User:
    """
    Регистрирует нового пользователя.

    Бросает UserAlreadyExistsError, если username занят.
    Бросает InvalidGoalError, если в goals есть неизвестный код.

    Дополнительная Pydantic-валидация уже проверила формат данных
    (длины, паттерн username, диапазон level). Здесь — бизнес-валидации.
    """
    # Проверка целей. Pydantic-схема через Literal уже ограничивает значения,
    # но добавим runtime-валидацию на случай прямого вызова service.
    invalid = set(goals) - VALID_GOALS
    if invalid:
        raise InvalidGoalError(f"Unknown goals: {', '.join(invalid)}")

    # Проверка уникальности username
    existing = db.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()
    if existing is not None:
        raise UserAlreadyExistsError(f"Username '{username}' is already taken")

    # Создаём пользователя
    user = User(
        username=username,
        display_name=display_name,
        level=level,
    )
    # Добавляем цели через relationship (дубликаты в goals автоматически
    # отсеиваются через set)
    for goal_code in set(goals):
        user.goals.append(UserGoal(goal=goal_code))

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def login_user(db: Session, username: str) -> User:
    """
    Вход по username (упрощённая авторизация без пароля).

    Если пользователя нет — бросает UserNotFoundError.
    """
    user = db.execute(
        select(User).where(User.username == username)
    ).scalar_one_or_none()
    if user is None:
        raise UserNotFoundError(f"User '{username}' not found")
    return user


def get_user_by_id(db: Session, user_id: int) -> User:
    """Загружает пользователя по ID, бросает UserNotFoundError если нет."""
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(f"User id={user_id} not found")
    return user


def user_to_dict(user: User) -> dict:
    """
    Преобразует ORM-объект в dict для Pydantic-схемы UserRead.
    Нужно, потому что у UserRead поле goals: list[str], а в ORM это
    list[UserGoal]. Также форматируем дату в ISO-строку.
    """
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "level": user.level,
        "goals": [g.goal for g in user.goals],
        "created_at": user.created_at.replace(tzinfo=timezone.utc).isoformat()
            if user.created_at else "",
    }

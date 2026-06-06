"""
SQLAlchemy-модели для БД пользователей (users.db).

Эти модели описывают пользовательскую часть системы:
  - User — сам пользователь (профиль)
  - UserGoal — цели изучения (M:N через secondary)

В отличие от моделей словаря, эти таблицы СОЗДАЁМ через ORM (init_users_db
вызывается при старте приложения, если БД пустая). Словарь же создаётся
отдельным скриптом load_to_sqlite.py.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Integer, DateTime, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from api.database import UsersBase


class User(UsersBase):
    """
    Профиль пользователя.

    Согласно ERD дипломного проекта, пользователь имеет:
      - username (логин, уникальный)
      - имя для отображения
      - уровень владения языком (1=новичок, 2=HSK1-2, 3=HSK3-4, 4=HSK5-6)
      - цели изучения (см. отдельную таблицу UserGoal)
      - дата регистрации

    Пароль и email пока опущены — упрощённая авторизация для MVP.
    В дипломной работе фиксируем как "MVP идентификации; полная авторизация
    с паролями и подтверждением email — в развитии проекта".
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Уникальный логин (латиница, цифры, _)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # Имя для отображения (может быть с пробелами, кириллицей, эмодзи)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Уровень владения китайским:
    #   1 — новичок (полный ноль)
    #   2 — HSK 1-2
    #   3 — HSK 3-4
    #   4 — HSK 5-6
    # NULL = пользователь выбрал "пройти тест", уровень будет определён позже.
    level: Mapped[Optional[int]] = mapped_column(
        Integer,
        CheckConstraint("level BETWEEN 1 AND 4"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )

    # Связи
    goals: Mapped[list["UserGoal"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}')>"


class UserGoal(UsersBase):
    """
    Цели изучения языка у пользователя.

    Это связь M:N между User и набором фиксированных целей. Цели хранятся
    строками-кодами (например, 'travel', 'business'), чтобы не плодить
    отдельную таблицу справочника на 6 строк. Список валидных значений
    проверяется на уровне Pydantic-схемы.

    У одного пользователя может быть несколько целей.
    """

    __tablename__ = "user_goals"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    goal: Mapped[str] = mapped_column(String(30), primary_key=True)

    user: Mapped["User"] = relationship(back_populates="goals")


# Допустимые значения цели. Используется и в Pydantic-схемах, и в frontend.
# Если в будущем добавим новые цели — правим в одном месте.
VALID_GOALS = frozenset({
    "travel",       # путешествия
    "business",     # бизнес и работа
    "culture",      # культура, кино, дорамы
    "study",        # учёба (вуз, школа)
    "relocation",   # переезд, эмиграция
    "hobby",        # для души, хобби
})

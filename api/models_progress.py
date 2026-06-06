"""
SQLAlchemy-модель для отслеживания прогресса изучения слов.

Хранится в users.db, потому что это персональные данные конкретного
пользователя (а не часть словаря).

Архитектурно поддерживает простой подход (записываем "знаю/учу" вручную)
и заложены поля для будущего spaced repetition (algorithm-driven).
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from api.database import UsersBase


class LearningProgress(UsersBase):
    """
    Запись о том, как пользователь изучает конкретное слово.

    Уникальность (user_id, word_id) означает: для каждого слова у каждого
    пользователя ровно одна запись прогресса. Когда пользователь видит
    слово первый раз — создаём запись; при последующих ответах — обновляем
    счётчики.

    Поля:
      times_seen — сколько всего раз слово показывалось в тренировке
      times_known — сколько раз пользователь нажал "Знаю"
      streak — текущая серия "знаю" подряд (сбрасывается на "учу")
      is_learned — флаг "выучено окончательно"
                   (выставляется когда streak >= 3, сбрасывается на "учу")
      last_reviewed_at — для будущего spaced repetition (когда показать снова)

    Логика "выучено":
      Если пользователь 3 раза подряд отметил слово как "знаю" — оно
      помечается как выученное (is_learned=True). Это эвристика — достаточно
      для MVP, но в Anki/SRS используется более сложный алгоритм.
    """
    __tablename__ = "learning_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "word_id", name="uq_user_word_progress"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # word_id указывает на bkrs.db — без FK (cross-database)
    word_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    times_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    times_known: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Используем Integer 0/1 вместо Boolean — некоторые SQLite-конфигурации
    # делают это удобнее для агрегации
    is_learned: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"<LearningProgress(user={self.user_id}, word={self.word_id}, "
            f"seen={self.times_seen}, known={self.times_known}, "
            f"learned={bool(self.is_learned)})>"
        )

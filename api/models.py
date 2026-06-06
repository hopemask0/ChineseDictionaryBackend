"""
SQLAlchemy 2.0 ORM-модели.

Каждый класс соответствует одной таблице в БД (см. schema.sql).
Используем современный стиль с Mapped[] и mapped_column() — это новый API
SQLAlchemy 2.0 с полноценной поддержкой типов.

Связи между таблицами (relationships):
  Word ──┬── 1:N ── Meaning ── 1:N ── Example
         ├── M:N ── Label (через WordLabel)
         └── 1:N ── WordReference

ORM-модели НЕ создают таблицы — таблицы уже созданы скриптом load_to_sqlite.py
по schema.sql. Эти классы просто описывают, как мапить существующие таблицы
на Python-объекты.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import ForeignKey, String, Integer, DateTime, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class Word(Base):
    """Словарная статья (одно китайское слово)."""

    __tablename__ = "words"

    id: Mapped[int] = mapped_column(primary_key=True)
    headword: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    pinyin: Mapped[Optional[str]] = mapped_column(String)
    pinyin_plain: Mapped[Optional[str]] = mapped_column(String)
    hsk_level: Mapped[Optional[int]] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String, default="common")
    char_length: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # === Связи ===
    # cascade="all, delete-orphan" означает: при удалении слова автоматически
    # удалятся все его значения, помеченные пометы и т.д.
    # lazy="selectin" — стратегия загрузки. selectin делает один доп. запрос
    # для всех связанных объектов разом, что быстрее, чем lazy="select".
    meanings: Mapped[list["Meaning"]] = relationship(
        back_populates="word",
        cascade="all, delete-orphan",
        order_by="Meaning.position",
        lazy="selectin",
    )

    # Many-to-many через secondary-таблицу word_labels
    labels: Mapped[list["Label"]] = relationship(
        secondary="word_labels",
        back_populates="words",
        lazy="selectin",
    )

    references: Mapped[list["WordReference"]] = relationship(
        back_populates="from_word",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        # Удобно для отладки в консоли SQLAlchemy
        return f"<Word(id={self.id}, headword='{self.headword}')>"


class Meaning(Base):
    """Одно значение слова. У слова может быть несколько значений."""

    __tablename__ = "meanings"

    id: Mapped[int] = mapped_column(primary_key=True)
    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1)
    translation: Mapped[str] = mapped_column(String, nullable=False)

    word: Mapped["Word"] = relationship(back_populates="meanings")
    examples: Mapped[list["Example"]] = relationship(
        back_populates="meaning",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Example(Base):
    """Пример использования слова на китайском с переводом."""

    __tablename__ = "examples"

    id: Mapped[int] = mapped_column(primary_key=True)
    meaning_id: Mapped[int] = mapped_column(
        ForeignKey("meanings.id", ondelete="CASCADE"), nullable=False
    )
    chinese: Mapped[str] = mapped_column(String, nullable=False)
    russian: Mapped[Optional[str]] = mapped_column(String)

    meaning: Mapped["Meaning"] = relationship(back_populates="examples")


class Label(Base):
    """Грамматическая или тематическая помета: "бот.", "мед.", "ист." и т.д."""

    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    words: Mapped[list["Word"]] = relationship(
        secondary="word_labels",
        back_populates="labels",
    )


class WordLabel(Base):
    """
    Связующая таблица для M:N между Word и Label.
    Не описываем relationships здесь — связь идёт через secondary='word_labels'
    в моделях Word и Label.
    """
    __tablename__ = "word_labels"

    word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[int] = mapped_column(
        ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True
    )


class WordReference(Base):
    """
    Перекрёстная ссылка из одной статьи на другое слово.
    Соответствует тегу [ref]другое_слово[/ref] в DSL.
    """
    __tablename__ = "word_references"

    from_word_id: Mapped[int] = mapped_column(
        ForeignKey("words.id", ondelete="CASCADE"), primary_key=True
    )
    to_headword: Mapped[str] = mapped_column(String, primary_key=True)

    from_word: Mapped["Word"] = relationship(back_populates="references")

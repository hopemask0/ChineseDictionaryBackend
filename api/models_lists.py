"""
SQLAlchemy-модели для системы списков слов.

Архитектура двухуровневая (паттерн "template + instance"):

  word_list_templates       — каталог СИСТЕМНЫХ списков (готовые наборы лексики).
                              Создаются нами, пользователь только просматривает.
                              Примеры: "Для путешествий", "Бизнес-лексика",
                              "Базовая HSK 1".

  word_list_template_items  — слова в системных списках.

  user_lists                — ПОЛЬЗОВАТЕЛЬСКИЕ списки.
                              Создаются двумя способами:
                                1. С нуля ("создать пустой список")
                                2. Подпиской на системный шаблон —
                                   слова шаблона копируются в новый user_list
                                   с пометкой source_template_id (для истории)
                              После создания пользователь может редактировать
                              даже скопированный список.

  user_list_items           — слова в пользовательских списках.

ВАЖНО: word_list_templates лежат в БД ПОЛЬЗОВАТЕЛЕЙ (users.db), а не словаря.
Логика: словарь — это read-only "большая внешняя БД" (БКРС), а наши
системные списки — это часть нашего приложения, мы их создаём и можем менять.
Также users.db маленькая и легко бэкапится вместе со списками пользователей.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime, ForeignKey, Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from api.database import UsersBase


# ============================================================================
# СИСТЕМНЫЕ ШАБЛОНЫ (template)
# ============================================================================

class WordListTemplate(UsersBase):
    """
    Шаблон системного тематического списка.

    Создаётся через сид-скрипт при инициализации БД. Пользователь видит
    эти списки в "Каталоге" и может подписаться на любой — это создаст
    редактируемую копию у него в "Моих списках".
    """
    __tablename__ = "word_list_templates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Системный идентификатор (slug), по нему мы апдейтим существующие
    # записи при пере-сидинге, не дублируя.
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # Эмодзи или короткий значок для UI (например, "✈️")
    icon: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Категория для группировки в каталоге.
    # Возможные значения: 'travel', 'business', 'culture', 'study', 'daily'.
    # Не строгая FK, чтобы добавлять новые категории без миграций.
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="daily")

    # Сортировочный вес — чем меньше, тем выше в каталоге.
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    items: Mapped[list["WordListTemplateItem"]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<WordListTemplate({self.slug}, '{self.title}')>"


class WordListTemplateItem(UsersBase):
    """
    Слово в системном шаблоне.

    word_id — это ID слова в bkrs.db (другая БД!). FK здесь не делаем,
    потому что SQLite не поддерживает cross-database FK, и логически
    это правильно: словарь — отдельная "вселенная".
    """
    __tablename__ = "word_list_template_items"

    template_id: Mapped[int] = mapped_column(
        ForeignKey("word_list_templates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    word_id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Порядковый номер внутри списка (для сортировки)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    template: Mapped["WordListTemplate"] = relationship(back_populates="items")


# ============================================================================
# ПОЛЬЗОВАТЕЛЬСКИЕ СПИСКИ (instance)
# ============================================================================

class UserList(UsersBase):
    """
    Пользовательский список слов.

    Может быть:
      - Создан пустым с нуля (source_template_id IS NULL)
      - Создан копией системного шаблона (source_template_id = ID шаблона).
        В этом случае при создании сразу копируются все слова шаблона.

    В любом случае после создания список полностью принадлежит пользователю —
    он может добавлять и удалять слова.
    """
    __tablename__ = "user_lists"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    # Если NULL — пользовательский список с нуля.
    # Если есть — это копия системного шаблона (метка для UI: "из каталога").
    source_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("word_list_templates.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False,
    )

    items: Mapped[list["UserListItem"]] = relationship(
        back_populates="user_list",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="UserListItem.position",
    )

    def __repr__(self) -> str:
        return f"<UserList(id={self.id}, user_id={self.user_id}, '{self.title}')>"


class UserListItem(UsersBase):
    """
    Слово в пользовательском списке.

    Уникальность (user_list_id, word_id) гарантирует, что одно слово
    нельзя добавить в список дважды.
    """
    __tablename__ = "user_list_items"
    __table_args__ = (
        UniqueConstraint("user_list_id", "word_id", name="uq_user_list_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_list_id: Mapped[int] = mapped_column(
        ForeignKey("user_lists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    word_id: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False,
    )

    user_list: Mapped["UserList"] = relationship(back_populates="items")

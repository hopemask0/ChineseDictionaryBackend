"""
SQLAlchemy-модели для данных Make Me a Hanzi.

Две таблицы, хранятся в той же bkrs.db (это всё ещё "словарные" данные,
read-only, не меняются в рантайме):

  characters       — этимология, декомпозиция, радикал, определение
  character_strokes — SVG-пути и медианы для анимации написания

Разделение на две таблицы — это намеренная оптимизация:
  - Этимология (~600 байт на иероглиф) запрашивается часто
  - Штрихи (~3-4 КБ на иероглиф) запрашиваются только когда пользователь
    хочет посмотреть анимацию

Источник: https://github.com/skishore/makemeahanzi (CC-BY 4.0)
"""
from typing import Optional

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from api.database import DictionaryBase


class Character(DictionaryBase):
    """
    Информация об одиночном иероглифе для блока "Структура".

    Все строковые поля могут быть пустыми/null — данные Make Me a Hanzi
    содержат разный набор для разных иероглифов.
    """
    __tablename__ = "characters"

    # Сам иероглиф как primary key — естественный уникальный ключ
    character: Mapped[str] = mapped_column(String(8), primary_key=True)

    # Список пиньинь в JSON-массиве, обычно одна-две вариации:
    # '["hǎo"]' или '["hǎo", "hào"]'
    pinyin_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Англоязычное определение от Make Me a Hanzi
    # (русское у нас уже есть в meanings, тут — для контекста этимологии)
    definition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Декомпозиция в нотации IDS, например: "⿰女子" значит "слева 女, справа 子"
    decomposition: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # Радикал — ключ иероглифа
    radical: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    # Тип этимологии: "pictographic" / "ideographic" / "pictophonetic"
    etymology_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Текстовое описание этимологии
    etymology_hint: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Семантическая часть (для pictophonetic — какая часть отвечает за смысл)
    etymology_semantic: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    # Фонетическая часть (для pictophonetic — какая часть отвечает за звук)
    etymology_phonetic: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    def __repr__(self) -> str:
        return f"<Character({self.character})>"


class CharacterStrokes(DictionaryBase):
    """
    Данные SVG-штрихов для анимации написания.

    strokes_json — JSON-массив SVG path-строк, каждая для одной черты
    medians_json — JSON-массив массивов точек (центральные линии штрихов)

    Эти данные передаются клиенту, который через hanzi-writer.js (в WebView)
    анимирует написание иероглифа.
    """
    __tablename__ = "character_strokes"

    character: Mapped[str] = mapped_column(String(8), primary_key=True)

    # JSON-массив SVG path-строк
    strokes_json: Mapped[str] = mapped_column(Text, nullable=False)

    # JSON-массив массивов координат для анимации движения кисти
    medians_json: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"<CharacterStrokes({self.character}, {len(self.strokes_json or '')} bytes)>"

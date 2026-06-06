"""
Бизнес-логика для работы с данными иероглифов (этимология + штрихи).
"""
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models_characters import Character, CharacterStrokes


class CharacterNotFoundError(Exception):
    """Иероглиф не найден в БД (Make Me a Hanzi покрывает ~9000 иероглифов)."""
    pass


def get_character(db: Session, ch: str) -> dict:
    """
    Возвращает информацию об иероглифе в формате, готовом для CharacterInfo.
    Бросает CharacterNotFoundError, если иероглифа нет в нашей БД.
    """
    char = db.execute(
        select(Character).where(Character.character == ch)
    ).scalar_one_or_none()

    if char is None:
        raise CharacterNotFoundError(f"Character '{ch}' not found in database")

    # Проверяем наличие данных штрихов (отдельная таблица)
    has_strokes = db.execute(
        select(CharacterStrokes.character).where(CharacterStrokes.character == ch)
    ).scalar_one_or_none() is not None

    pinyin_list: list[str] = []
    if char.pinyin_json:
        try:
            pinyin_list = json.loads(char.pinyin_json)
        except json.JSONDecodeError:
            pinyin_list = []

    return {
        "character": char.character,
        "pinyin": pinyin_list,
        "definition": char.definition,
        "decomposition": char.decomposition,
        "radical": char.radical,
        "etymology_type": char.etymology_type,
        "etymology_hint": char.etymology_hint,
        "etymology_semantic": char.etymology_semantic,
        "etymology_phonetic": char.etymology_phonetic,
        "has_strokes": has_strokes,
    }


def get_character_strokes(db: Session, ch: str) -> dict:
    """
    Возвращает данные штрихов для анимации иероглифа.
    Бросает CharacterNotFoundError, если данных нет.
    """
    strokes = db.execute(
        select(CharacterStrokes).where(CharacterStrokes.character == ch)
    ).scalar_one_or_none()

    if strokes is None:
        raise CharacterNotFoundError(f"Strokes for '{ch}' not found")

    return {
        "character": strokes.character,
        "strokes": json.loads(strokes.strokes_json),
        "medians": json.loads(strokes.medians_json),
    }


def get_characters_in_word(db: Session, word: str) -> list[dict]:
    """
    Возвращает информацию по каждому иероглифу в составе слова.
    
    Например, для 学习 вернёт информацию по 学 и по 习.
    Если какого-то иероглифа нет в нашей БД — пропускаем (не падаем).
    Используется для блока "Структура" на карточке составного слова.
    """
    result = []
    for ch in word:
        if not _is_chinese_ideograph(ch):
            continue
        try:
            result.append(get_character(db, ch))
        except CharacterNotFoundError:
            continue
    return result


def _is_chinese_ideograph(ch: str) -> bool:
    """Проверка: является ли символ китайским иероглифом."""
    # Основной блок CJK Unified Ideographs + Extension A
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF or
        0x3400 <= code <= 0x4DBF
    )

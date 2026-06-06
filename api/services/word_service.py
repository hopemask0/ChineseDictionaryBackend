"""
Сервис для подбора случайных слов (например, для "слова дня" на главном экране).

Алгоритмический момент:
  Простой ORDER BY RANDOM() на 3.4 млн строк выполняется ~3-5 секунд.
  Для главного экрана это недопустимо.

  Используем приём "случайный rowid":
    1. Узнаём минимальный и максимальный id среди подходящих слов.
    2. Выбираем случайное число в этом диапазоне.
    3. Берём первое подходящее слово с id >= этого числа.

  Сложность — O(log N) за счёт индекса по id.
  Время выполнения — единицы миллисекунд.
"""
import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models import Word


class NoWordsFoundError(Exception):
    """Нет ни одного слова, подходящего под критерии."""
    pass


def get_random_word(
    db: Session,
    min_char_length: int = 1,
    max_char_length: int = 3,
    require_pinyin: bool = True,
    category: str | None = "common",
    hsk_level: int | None = None,
) -> Word:
    """
    Возвращает случайное слово, подходящее под фильтры.

    Параметры по умолчанию настроены для "слова дня":
      - 1-3 иероглифа (короткие, легко запомнить)
      - С пиньинь (чтобы пользователь знал, как читать)
      - Только common-категория (не имена собственные и не редкие термины)

    Если задан hsk_level — фильтруем по уровню. Иначе уровень не учитываем.
    """
    # Строим условия фильтрации
    conditions = [
        Word.char_length >= min_char_length,
        Word.char_length <= max_char_length,
    ]
    if require_pinyin:
        conditions.append(Word.pinyin.isnot(None))
    if category is not None:
        conditions.append(Word.category == category)
    if hsk_level is not None:
        conditions.append(Word.hsk_level == hsk_level)

    # Узнаём минимальный и максимальный id среди подходящих слов
    min_id, max_id = db.execute(
        select(func.min(Word.id), func.max(Word.id)).where(*conditions)
    ).one()

    if min_id is None or max_id is None:
        raise NoWordsFoundError("No words match the criteria")

    # Выбираем случайный id в диапазоне и ищем ближайшее слово
    # Делаем до 5 попыток на случай, если в выбранном "регионе" id
    # вдруг нет подходящих слов (маловероятно, но возможно при
    # экзотических фильтрах).
    for _ in range(5):
        random_id = random.randint(min_id, max_id)
        word = db.execute(
            select(Word)
            .where(*conditions, Word.id >= random_id)
            .order_by(Word.id)
            .limit(1)
        ).scalar_one_or_none()
        if word is not None:
            return word

    # Если за 5 попыток не нашли — последний fallback: ORDER BY RANDOM
    # на сильно отфильтрованной выборке (это уже быстро).
    word = db.execute(
        select(Word).where(*conditions).order_by(func.random()).limit(1)
    ).scalar_one_or_none()

    if word is None:
        raise NoWordsFoundError("No words match the criteria")
    return word

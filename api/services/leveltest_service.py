"""
Бизнес-логика входного HSK-теста.

Алгоритм:
  - На запрос get_questions(hsk_level, count=10) возвращаем count вопросов
    указанного HSK уровня
  - Вопросы перемешаны по типам: 6 multiple-choice перевода,
    3 multiple-choice иероглифа, 1 ввод текста
  - Дистракторы (неправильные варианты) — случайные слова того же HSK уровня

Клиент сам решает, повышать ли уровень после набора вопросов (>=60%).
"""
import random
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import Word
from api.translation_utils import get_meaningful_translations


# Распределение типов вопросов в одном пакете из 10:
#   6 choose_translation, 3 choose_hanzi, 1 type_translation
# Это даёт разнообразие, но не нагружает пользователя множеством текстовых вводов
QUESTION_TYPES_DISTRIBUTION = (
    ["choose_translation"] * 6 +
    ["choose_hanzi"] * 3 +
    ["type_translation"] * 1
)


def _hsk_to_db_level(hsk_level: int) -> int:
    """
    Маппит HSK уровень (1-6, как в блок-схеме теста) к значению поля
    hsk_level в нашей БД (которое после переразметки хранит app-уровни 2-4).

    Соответствие:
      HSK 1, 2 → db_level=2 (HSK 1-2 в нашей шкале)
      HSK 3, 4 → db_level=3 (HSK 3-4 в нашей шкале)
      HSK 5, 6 → db_level=4 (HSK 5-6 в нашей шкале)

    Это компромисс между блок-схемой теста (6 уровней) и хранилищем
    (3 группы). Для пользователя тест остаётся 6-ступенчатым, но при
    запросе HSK 1 и HSK 2 мы берём слова из одного пула. Точность
    различения "HSK 1 vs HSK 2" теряется, но в рамках MVP это допустимо.

    В будущем (см. backlog "доработка словаря") можно добавить отдельное
    поле original_hsk_level (1-6) при переразметке и сделать точное
    разделение.
    """
    if hsk_level in (1, 2):
        return 2
    if hsk_level in (3, 4):
        return 3
    return 4  # HSK 5, 6


class NotEnoughWordsError(Exception):
    """В БД недостаточно слов нужного уровня."""
    pass


def get_questions(
    dict_db: Session, hsk_level: int, count: int = 10,
) -> dict:
    """
    Возвращает пакет из count вопросов для теста на указанном HSK уровне.

    Стратегия:
      1. Загружаем `count + ~20 буфер` подходящих слов (с переводом)
      2. Из них выбираем `count` целевых слов
      3. Остальные используем как дистракторы для multiple choice
      4. Раскидываем по типам вопросов согласно распределению
    """
    # Маппим запрашиваемый HSK уровень в значение из нашей БД
    db_level = _hsk_to_db_level(hsk_level)

    # Шаг 1: загружаем случайные кандидаты-слова нужного уровня.
    # Берём с запасом (count + 20), потому что часть отсеется на шаге 2.
    word_rows = dict_db.execute(
        select(Word.id, Word.headword, Word.pinyin)
        .where(
            Word.hsk_level == db_level,
            Word.category == "common",
        )
        .order_by(_random_func(dict_db))
        .limit(count + 20)
    ).all()

    if not word_rows:
        raise NotEnoughWordsError(
            f"No common words found for HSK {hsk_level} (db_level={db_level})"
        )

    # Шаг 2: для каждого слова находим первое ОСМЫСЛЕННОЕ значение.
    # Фильтрация в Python — надёжнее SQL GLOB для крайних случаев.
    word_ids = [r[0] for r in word_rows]
    meaningful = get_meaningful_translations(dict_db, word_ids)

    # Собираем валидные кандидаты: те, у кого нашли осмысленный перевод
    valid = []
    for wid, hw, py in word_rows:
        tr = meaningful.get(wid)
        if tr:
            valid.append((wid, hw, py, tr))

    if len(valid) < count + 3:
        raise NotEnoughWordsError(
            f"Not enough words for HSK {hsk_level}: have {len(valid)}, need {count + 3}"
        )

    # Делим: целевые слова + пул дистракторов
    target_words = valid[:count]
    distractor_pool = valid[count:]

    # Распределяем по типам и перемешиваем
    types = QUESTION_TYPES_DISTRIBUTION.copy()
    random.shuffle(types)

    questions = []
    for i, (wid, hanzi, pinyin, translation) in enumerate(target_words):
        qtype = types[i] if i < len(types) else "choose_translation"
        q = _build_question(
            qtype=qtype,
            word=(wid, hanzi, pinyin, translation),
            distractors=distractor_pool,
        )
        questions.append(q)

    return {
        "hsk_level": hsk_level,
        "questions": questions,
    }


def _build_question(qtype: str, word: tuple, distractors: list) -> dict:
    """
    Строит один вопрос указанного типа на основе целевого слова и пула
    дистракторов.
    """
    wid, hanzi, pinyin, translation = word
    short_translation = _shorten_translation(translation)

    if qtype == "choose_translation":
        # Показан иероглиф + пиньинь, выбрать перевод
        wrong = _pick_distractors(distractors, n=3, exclude_id=wid, field="translation")
        wrong_texts = [_shorten_translation(t) for t in wrong]
        choices = wrong_texts + [short_translation]
        random.shuffle(choices)
        return {
            "question_type": qtype,
            "word_id": wid,
            "hanzi": hanzi,
            "pinyin": pinyin,
            "correct_answer": short_translation,
            "choices": choices,
            "accepted_answers": [],
        }

    elif qtype == "choose_hanzi":
        # Показан перевод (correct_answer для UI), выбрать иероглиф (choices)
        # На клиенте isCorrect для CHOOSE_HANZI сравнивает выбор с полем hanzi.
        wrong = _pick_distractors(distractors, n=3, exclude_id=wid, field="hanzi")
        choices = wrong + [hanzi]
        random.shuffle(choices)
        return {
            "question_type": qtype,
            "word_id": wid,
            "hanzi": hanzi,
            "pinyin": pinyin,
            # Для UI: показываем перевод, чтобы пользователь знал что искать
            "correct_answer": short_translation,
            "choices": choices,
            "accepted_answers": [],
        }

    else:  # type_translation
        # Показан иероглиф + пиньинь, ввести перевод текстом
        # accepted_answers — все варианты (для проверки на клиенте)
        accepted = _extract_accepted_answers(translation)
        return {
            "question_type": qtype,
            "word_id": wid,
            "hanzi": hanzi,
            "pinyin": pinyin,
            "correct_answer": short_translation,
            "choices": [],
            "accepted_answers": accepted,
        }


def _pick_distractors(pool: list, n: int, exclude_id: int, field: str) -> list[str]:
    """Возвращает n текстов дистракторов из пула."""
    filtered = [item for item in pool if item[0] != exclude_id]
    sample = random.sample(filtered, min(n, len(filtered)))
    if field == "translation":
        return [item[3] for item in sample]
    else:  # hanzi
        return [item[1] for item in sample]


def _shorten_translation(translation: str) -> str:
    """
    Сокращает многозначный перевод до первого значения для multiple choice.
    Пример: "учиться; заниматься; учеба" → "учиться"
    """
    if not translation:
        return ""
    # Берём текст до первого разделителя ; или ,
    for sep in [";", ",", "(", "—"]:
        if sep in translation:
            translation = translation.split(sep)[0]
            break
    return translation.strip()


def _extract_accepted_answers(translation: str) -> list[str]:
    """
    Извлекает все приемлемые ответы из строки перевода.
    Используется для проверки текстового ввода.

    Пример: "учиться; заниматься (чем-л.); учеба" →
            ["учиться", "заниматься", "учеба"]

    Каждый вариант приводится к lowercase и очищается от пунктуации,
    чтобы пользователь мог ввести в любом регистре без точек/запятых.
    """
    if not translation:
        return []

    # Разбиваем по основным разделителям
    parts = re.split(r"[;,]", translation)

    accepted = []
    for part in parts:
        # Убираем скобки и всё внутри
        cleaned = re.sub(r"\([^)]*\)", "", part)
        cleaned = _normalize(cleaned)
        if cleaned and cleaned not in accepted:
            accepted.append(cleaned)

    return accepted


def _normalize(text: str) -> str:
    """Lowercase + убирает диакритику + лишние пробелы."""
    text = text.lower().strip()
    # Убираем диакритические знаки (например, ё → е, но это спорно — оставим ё)
    text = text.replace("ё", "е")
    # Убираем точки в конце
    text = text.rstrip(".!?")
    # Сжимаем пробелы
    text = re.sub(r"\s+", " ", text)
    return text


def _random_func(db: Session):
    """
    Возвращает SQL-функцию случайной сортировки.
    SQLite использует RANDOM(), PostgreSQL и большинство других — RANDOM().
    """
    from sqlalchemy import func
    return func.random()


# ============================================================================
# Сохранение результата
# ============================================================================

def map_hsk_to_app_level(hsk_level: int) -> int:
    """
    Маппит HSK уровень (1-6) в шкалу нашего приложения (1-4).

    Шкала приложения (см. domain/model/User.kt::Level):
      1 = BEGINNER (новичок, не прошёл даже HSK 1)
      2 = HSK 1-2
      3 = HSK 3-4
      4 = HSK 5-6
    """
    if hsk_level <= 0:
        return 1
    if hsk_level in (1, 2):
        return 2
    if hsk_level in (3, 4):
        return 3
    return 4  # HSK 5-6


def save_level(users_db: Session, user_id: int, hsk_level: int) -> int:
    """
    Сохраняет определённый уровень в профиль пользователя.
    Возвращает app_level (1-4) для синхронизации с клиентом.
    """
    from api.models_users import User
    user = users_db.execute(
        select(User).where(User.id == user_id)
    ).scalar_one_or_none()
    if user is None:
        raise ValueError(f"User {user_id} not found")

    app_level = map_hsk_to_app_level(hsk_level)
    user.level = app_level
    users_db.commit()
    return app_level
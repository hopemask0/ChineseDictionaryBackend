"""
Бизнес-логика для прогресса изучения слов.

Два уровня логики:
  1. Запись ответа на одно слово — обновление счётчиков с правилами
     (streak, is_learned).
  2. Подготовка сессии тренировки по списку — собираем слова списка + их
     прогресс одним запросом.
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.models import Word
from api.models_lists import UserList, UserListItem
from api.models_progress import LearningProgress
from api.translation_utils import get_meaningful_translations


# Сколько раз подряд нужно ответить "знаю", чтобы слово стало "выученным"
LEARNED_THRESHOLD = 3


class ListNotFoundError(Exception):
    pass


def record_answer(
    users_db: Session, user_id: int, word_id: int, knows: bool,
) -> dict:
    """
    Записывает ответ пользователя на одно слово.

    Если записи прогресса ещё нет — создаём.
    Иначе обновляем счётчики.

    Правила:
      knows=True  → times_known+1, streak+1, если streak>=3 → is_learned=True
      knows=False → streak=0, is_learned=False (откатываем "выученность")
    """
    progress = users_db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.word_id == word_id,
        )
    ).scalar_one_or_none()

    if progress is None:
        progress = LearningProgress(
            user_id=user_id,
            word_id=word_id,
            times_seen=0,
            times_known=0,
            streak=0,
            is_learned=0,
        )
        users_db.add(progress)

    progress.times_seen += 1
    progress.last_reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    if knows:
        progress.times_known += 1
        progress.streak += 1
        if progress.streak >= LEARNED_THRESHOLD:
            progress.is_learned = 1
    else:
        progress.streak = 0
        progress.is_learned = 0  # сбрасываем — слово снова "учится"

    users_db.commit()
    users_db.refresh(progress)

    return {
        "word_id": progress.word_id,
        "times_seen": progress.times_seen,
        "times_known": progress.times_known,
        "streak": progress.streak,
        "is_learned": bool(progress.is_learned),
        "last_reviewed_at": (
            progress.last_reviewed_at.replace(tzinfo=timezone.utc).isoformat()
            if progress.last_reviewed_at else None
        ),
    }


def prepare_session(
    users_db: Session, dict_db: Session, user_id: int, list_id: int,
) -> dict:
    """
    Готовит сет карточек для тренировки по конкретному списку.

    Берёт все слова из списка, обогащает их пиньинем + переводом из БКРС,
    и прикрепляет к каждой карточке текущий прогресс пользователя.

    Карточки возвращаются в "перетасованном" порядке для разнообразия —
    но в простом порядке (сортировки нет, просто как в списке).
    Полную случайность пользователь получит, нажав на следующей итерации.
    """
    # Проверяем, что список существует и принадлежит пользователю
    user_list = users_db.execute(
        select(UserList).where(
            UserList.id == list_id, UserList.user_id == user_id,
        )
    ).scalar_one_or_none()
    if user_list is None:
        raise ListNotFoundError(f"List {list_id} not found for user {user_id}")

    # Берём word_id-ы из списка в их порядке
    items = users_db.execute(
        select(UserListItem.word_id, UserListItem.position)
        .where(UserListItem.user_list_id == list_id)
        .order_by(UserListItem.position)
    ).all()
    word_ids = [w for w, _ in items]

    if not word_ids:
        return {
            "list_id": list_id,
            "list_title": user_list.title,
            "cards": [],
        }

    # Шаг 1: базовая информация о словах (без translation)
    word_info = dict_db.execute(
        select(Word.id, Word.headword, Word.pinyin)
        .where(Word.id.in_(word_ids))
    ).all()
    # Шаг 2: первое осмысленное значение для каждого слова
    meaningful = get_meaningful_translations(dict_db, word_ids)
    # Собираем словарь wid → (headword, pinyin, перевод-или-None)
    words_dict = {
        wid: (hw, py, meaningful.get(wid))
        for wid, hw, py in word_info
    }

    # Берём прогресс по этим словам у текущего пользователя одним запросом
    progress_rows = users_db.execute(
        select(LearningProgress.word_id,
               LearningProgress.times_seen,
               LearningProgress.is_learned)
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.word_id.in_(word_ids),
        )
    ).all()
    progress_dict = {wid: (seen, bool(learned)) for wid, seen, learned in progress_rows}

    cards = []
    for word_id in word_ids:
        info = words_dict.get(word_id)
        if info is None:
            # Слово удалили из словаря — пропускаем
            continue
        headword, pinyin, translation = info
        seen, learned = progress_dict.get(word_id, (0, False))
        cards.append({
            "word_id": word_id,
            "headword": headword,
            "pinyin": pinyin,
            "translation": translation,
            "is_learned": learned,
            "times_seen": seen,
        })

    return {
        "list_id": list_id,
        "list_title": user_list.title,
        "cards": cards,
    }


def get_user_stats(users_db: Session, user_id: int) -> dict:
    """Сводная статистика прогресса для главного экрана."""
    # Сколько уникальных слов пользователь видел
    total_seen = users_db.execute(
        select(func.count())
        .select_from(LearningProgress)
        .where(LearningProgress.user_id == user_id)
    ).scalar() or 0

    # Сколько слов помечены как выученные
    total_learned = users_db.execute(
        select(func.count())
        .select_from(LearningProgress)
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.is_learned == 1,
        )
    ).scalar() or 0

    # Общее число ответов (сумма times_seen)
    total_reviews = users_db.execute(
        select(func.coalesce(func.sum(LearningProgress.times_seen), 0))
        .where(LearningProgress.user_id == user_id)
    ).scalar() or 0

    return {
        "total_seen": int(total_seen),
        "total_learned": int(total_learned),
        "total_reviews": int(total_reviews),
    }
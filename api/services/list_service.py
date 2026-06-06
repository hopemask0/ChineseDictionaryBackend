"""
Бизнес-логика для системы списков слов.

Принципы:
  - Все методы принимают user_id явно (зависимость авторизации — на роутерах)
  - Проверки прав ("это список текущего пользователя?") тоже здесь
  - Использует ОБЕ БД: users.db (списки) и bkrs.db (для проверки/обогащения слов)
"""
from datetime import timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from api.models import Word
from api.models_lists import (
    UserList, UserListItem, WordListTemplate, WordListTemplateItem,
)
from api.translation_utils import get_meaningful_translations


# ============================================================================
# Исключения
# ============================================================================

class ListNotFoundError(Exception):
    """Список не найден или не принадлежит текущему пользователю."""
    pass


class TemplateNotFoundError(Exception):
    """Системный шаблон не найден в каталоге."""
    pass


class WordNotInDictionaryError(Exception):
    """Слова с таким ID нет в БКРС — нельзя добавить в список."""
    pass


class WordAlreadyInListError(Exception):
    """Слово уже есть в этом списке."""
    pass


# ============================================================================
# Каталог системных шаблонов
# ============================================================================

def get_catalog(users_db: Session) -> list[dict]:
    """
    Возвращает все системные шаблоны для отображения в каталоге.
    Каждая запись содержит число слов в шаблоне.
    """
    # COUNT через подзапрос, чтобы получить word_count одним запросом
    count_subq = (
        select(WordListTemplateItem.template_id, func.count().label("cnt"))
        .group_by(WordListTemplateItem.template_id)
        .subquery()
    )
    rows = users_db.execute(
        select(WordListTemplate, count_subq.c.cnt)
        .outerjoin(count_subq, WordListTemplate.id == count_subq.c.template_id)
        .order_by(WordListTemplate.sort_order, WordListTemplate.id)
    ).all()

    return [
        {
            "id": tpl.id,
            "slug": tpl.slug,
            "icon": tpl.icon,
            "title": tpl.title,
            "description": tpl.description,
            "category": tpl.category,
            "word_count": cnt or 0,
        }
        for tpl, cnt in rows
    ]


# ============================================================================
# Пользовательские списки
# ============================================================================

def get_user_lists(users_db: Session, user_id: int) -> list[dict]:
    """
    Возвращает все списки пользователя для экрана "Мои списки".
    Каждая запись содержит число слов и информацию об источнике.
    """
    count_subq = (
        select(UserListItem.user_list_id, func.count().label("cnt"))
        .group_by(UserListItem.user_list_id)
        .subquery()
    )
    rows = users_db.execute(
        select(UserList, count_subq.c.cnt, WordListTemplate.slug)
        .outerjoin(count_subq, UserList.id == count_subq.c.user_list_id)
        .outerjoin(
            WordListTemplate,
            UserList.source_template_id == WordListTemplate.id,
        )
        .where(UserList.user_id == user_id)
        .order_by(UserList.created_at.desc())
    ).all()

    return [
        {
            "id": ul.id,
            "title": ul.title,
            "icon": ul.icon,
            "word_count": cnt or 0,
            "source_template_id": ul.source_template_id,
            "source_template_slug": slug,
            "created_at": ul.created_at.replace(tzinfo=timezone.utc).isoformat(),
        }
        for ul, cnt, slug in rows
    ]


def get_user_list_detail(
    users_db: Session, dict_db: Session, user_id: int, list_id: int,
) -> dict:
    """
    Возвращает полные данные списка вместе со всеми его словами.

    Слова берутся из bkrs.db с обогащением (пиньинь, первый перевод).
    """
    user_list = users_db.execute(
        select(UserList)
        .options(selectinload(UserList.items))
        .where(UserList.id == list_id, UserList.user_id == user_id)
    ).scalar_one_or_none()

    if user_list is None:
        raise ListNotFoundError(f"List {list_id} not found for user {user_id}")

    # Все word_id одним запросом
    word_ids = [item.word_id for item in user_list.items]
    words_dict: dict[int, tuple[str, str | None, str | None]] = {}
    if word_ids:
        # Шаг 1: базовая инфа о словах
        rows = dict_db.execute(
            select(Word.id, Word.headword, Word.pinyin)
            .where(Word.id.in_(word_ids))
        ).all()
        # Шаг 2: первое осмысленное значение каждого слова (фильтрация в Python)
        meaningful = get_meaningful_translations(dict_db, word_ids)
        for wid, hw, py in rows:
            words_dict[wid] = (hw, py, meaningful.get(wid))

    items = []
    for item in sorted(user_list.items, key=lambda x: x.position):
        info = words_dict.get(item.word_id)
        if info is None:
            # Слово удалили из словаря — пропускаем
            continue
        hw, py, tr = info
        items.append({
            "word_id": item.word_id,
            "position": item.position,
            "headword": hw,
            "pinyin": py,
            "first_translation": tr,
        })

    return {
        "id": user_list.id,
        "title": user_list.title,
        "icon": user_list.icon,
        "source_template_id": user_list.source_template_id,
        "created_at": user_list.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "items": items,
    }


def create_empty_list(
    users_db: Session, user_id: int, title: str, icon: str | None,
) -> UserList:
    """Создаёт пустой пользовательский список."""
    user_list = UserList(
        user_id=user_id,
        title=title.strip(),
        icon=icon,
        source_template_id=None,
    )
    users_db.add(user_list)
    users_db.commit()
    users_db.refresh(user_list)
    return user_list


def subscribe_to_template(
    users_db: Session,
    user_id: int,
    template_id: int,
    custom_title: str | None = None,
) -> UserList:
    """
    Создаёт пользовательский список как копию системного шаблона.
    Слова шаблона копируются в новый список с сохранением порядка.
    """
    template = users_db.execute(
        select(WordListTemplate)
        .options(selectinload(WordListTemplate.items))
        .where(WordListTemplate.id == template_id)
    ).scalar_one_or_none()

    if template is None:
        raise TemplateNotFoundError(f"Template {template_id} not found")

    user_list = UserList(
        user_id=user_id,
        title=(custom_title or template.title).strip(),
        icon=template.icon,
        source_template_id=template.id,
    )
    users_db.add(user_list)
    users_db.flush()  # получаем id для FK

    # Копируем слова в том же порядке
    for tpl_item in sorted(template.items, key=lambda x: x.position):
        users_db.add(UserListItem(
            user_list_id=user_list.id,
            word_id=tpl_item.word_id,
            position=tpl_item.position,
        ))

    users_db.commit()
    users_db.refresh(user_list)
    return user_list


def update_list(
    users_db: Session, user_id: int, list_id: int,
    title: str | None, icon: str | None,
) -> UserList:
    """Переименование или смена иконки списка."""
    user_list = _get_owned_list(users_db, user_id, list_id)
    if title is not None:
        user_list.title = title.strip()
    if icon is not None:
        user_list.icon = icon
    users_db.commit()
    users_db.refresh(user_list)
    return user_list


def delete_list(users_db: Session, user_id: int, list_id: int) -> None:
    """Удаляет список со всеми его словами."""
    user_list = _get_owned_list(users_db, user_id, list_id)
    users_db.delete(user_list)
    users_db.commit()


def add_word_to_list(
    users_db: Session, dict_db: Session,
    user_id: int, list_id: int, word_id: int,
) -> None:
    """
    Добавляет слово в список. Если слова нет в БКРС или оно уже в списке —
    бросает соответствующее исключение.
    """
    user_list = _get_owned_list(users_db, user_id, list_id)

    # Проверяем, что слово существует в БКРС
    word_exists = dict_db.execute(
        select(Word.id).where(Word.id == word_id)
    ).scalar_one_or_none() is not None
    if not word_exists:
        raise WordNotInDictionaryError(f"Word {word_id} not found in dictionary")

    # Проверяем, что слова ещё нет в списке
    existing = users_db.execute(
        select(UserListItem)
        .where(
            UserListItem.user_list_id == list_id,
            UserListItem.word_id == word_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise WordAlreadyInListError(f"Word {word_id} already in list {list_id}")

    # Определяем position — следующий после последнего
    max_pos = users_db.execute(
        select(func.max(UserListItem.position))
        .where(UserListItem.user_list_id == list_id)
    ).scalar() or 0

    users_db.add(UserListItem(
        user_list_id=list_id,
        word_id=word_id,
        position=max_pos + 1,
    ))
    users_db.commit()


def remove_word_from_list(
    users_db: Session, user_id: int, list_id: int, word_id: int,
) -> None:
    """Удаляет слово из списка."""
    _get_owned_list(users_db, user_id, list_id)  # проверка прав

    item = users_db.execute(
        select(UserListItem)
        .where(
            UserListItem.user_list_id == list_id,
            UserListItem.word_id == word_id,
        )
    ).scalar_one_or_none()
    if item is None:
        # Слова нет — не считаем ошибкой, idempotent delete
        return
    users_db.delete(item)
    users_db.commit()


# ============================================================================
# Хелперы
# ============================================================================

def _get_owned_list(users_db: Session, user_id: int, list_id: int) -> UserList:
    """
    Возвращает список, если он существует И принадлежит пользователю.
    Иначе ListNotFoundError. Это защита от ситуации, когда один пользователь
    пытается изменить список другого, подбирая ID в URL.
    """
    user_list = users_db.execute(
        select(UserList).where(
            UserList.id == list_id, UserList.user_id == user_id,
        )
    ).scalar_one_or_none()
    if user_list is None:
        raise ListNotFoundError(f"List {list_id} not found for user {user_id}")
    return user_list
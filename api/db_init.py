"""
Инициализация БД пользователей при первом запуске приложения.

Что делает:
  1. Создаёт users.db если не существует.
  2. Создаёт все таблицы по моделям из models_users.py и models_lists.py.
  3. Сидит каталог системных списков (если ещё не засидован).

Сидинг идемпотентный: повторный вызов не плодит дубликаты.
"""
from pathlib import Path

from sqlalchemy import select

# Импортируем все модели, чтобы зарегистрировать в UsersBase.metadata.
# Без этого create_all() о них не узнает.
from api import models_lists, models_progress, models_users  # noqa: F401
from api.database import UsersBase, UsersSessionLocal, users_engine
from api.models_lists import WordListTemplate, WordListTemplateItem


def init_users_database() -> None:
    """
    Создаёт users.db со всеми таблицами и сидит каталог системных списков.
    Безопасно вызывать многократно — существующие данные не теряются.
    """
    # Создаём папку для БД при необходимости
    db_url = str(users_engine.url)
    if db_url.startswith("sqlite:///"):
        db_path = Path(db_url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)

    # Создаём все таблицы. Существующие не трогаются.
    UsersBase.metadata.create_all(bind=users_engine)

    # Сидим каталог системных списков
    _seed_list_catalog()


# ============================================================================
# Каталог системных списков
# ============================================================================

# Слова для сидов взяты по принципу: общеупотребительные, есть в HSK 1-3
# (после нашей переразметки они точно есть в БД с category='common').
# ID указываются как ссылки на word_id в bkrs.db.
#
# ВАЖНО: эти ID — это конкретные ID в БД БКРС. Они могут отличаться от того,
# что у Нади в БД, если она пересоздавала словарь. Чтобы не зависеть от
# ID, ниже мы делаем lookup по headword (тексту иероглифа) при сидинге.

CATALOG = [
    {
        "slug": "travel-basic",
        "icon": "✈️",
        "title": "Путешественнику: базовое",
        "description": "Слова, которые понадобятся сразу по прилёте: «здравствуйте», «спасибо», «билет», «такси».",
        "category": "travel",
        "sort_order": 10,
        "words": [
            "你好", "谢谢", "对不起", "再见",
            "请", "票", "钱", "贵",
            "出租车", "饭店", "厕所", "水",
            "多少", "哪里", "什么", "几",
        ],
    },
    {
        "slug": "travel-food",
        "icon": "🥢",
        "title": "Путешественнику: еда",
        "description": "Заказать в кафе, спросить, что в блюде, найти любимый чай.",
        "category": "travel",
        "sort_order": 20,
        "words": [
            "菜单", "茶", "咖啡", "啤酒",
            "米饭", "面条", "肉", "鱼",
            "辣", "甜", "好吃", "饿",
            "买单", "服务员",
        ],
    },
    {
        "slug": "business-meeting",
        "icon": "💼",
        "title": "Бизнес: переговоры",
        "description": "Лексика для деловой встречи и обсуждения проекта.",
        "category": "business",
        "sort_order": 30,
        "words": [
            "公司", "经理", "合同", "项目",
            "会议", "讨论", "决定", "客户",
            "价格", "市场", "工作",
        ],
    },
    {
        "slug": "culture-festivals",
        "icon": "🏮",
        "title": "Культура: праздники",
        "description": "Слова о китайских традиционных праздниках и обычаях.",
        "category": "culture",
        "sort_order": 40,
        "words": [
            "春节", "中秋节", "国庆节", "节日",
            "传统", "文化", "庆祝", "家",
        ],
    },
    {
        "slug": "daily-greetings",
        "icon": "👋",
        "title": "Каждый день: приветствия",
        "description": "Базовые формы вежливости и общения.",
        "category": "daily",
        "sort_order": 50,
        "words": [
            "你好", "早上好", "晚上好", "再见",
            "谢谢", "不客气", "对不起", "没关系",
        ],
    },
    {
        "slug": "study-basics",
        "icon": "📚",
        "title": "Для учёбы: основное",
        "description": "Слова, которые встретишь в первые недели изучения китайского.",
        "category": "study",
        "sort_order": 60,
        "words": [
            "我", "你", "他", "她",
            "是", "不", "有", "没有",
            "学习", "学校", "老师", "学生",
            "中国", "中文",
        ],
    },
]


def _seed_list_catalog() -> None:
    """
    Создаёт системные списки в каталоге, если их ещё нет (или обновляет
    метаданные, если slug уже существует).

    Слова добавляются только при ПЕРВОМ создании списка. Если потом мы
    хотим обновить состав слов — нужно либо удалить шаблон, либо написать
    отдельную миграцию.

    word_id для каждого слова ищется в bkrs.db по тексту headword.
    Если слова в БКРС нет — пропускаем (например, "出租车" может быть
    в составной форме).
    """
    # Загружаем словарь раз, чтобы не дёргать БД на каждое слово
    from api.database import DictionarySessionLocal
    from api.models import Word

    headword_to_id: dict[str, int] = {}
    with DictionarySessionLocal() as dict_db:
        # Соберём все headword из всех шаблонов
        all_headwords = set()
        for tpl in CATALOG:
            all_headwords.update(tpl["words"])

        # Один запрос за всеми сразу — быстрее
        rows = dict_db.execute(
            select(Word.id, Word.headword).where(Word.headword.in_(all_headwords))
        ).all()
        headword_to_id = {hw: wid for wid, hw in rows}

    # Теперь сидим в users.db
    with UsersSessionLocal() as db:
        for tpl_data in CATALOG:
            slug = tpl_data["slug"]
            existing = db.execute(
                select(WordListTemplate).where(WordListTemplate.slug == slug)
            ).scalar_one_or_none()

            if existing is None:
                # Создаём шаблон
                tpl = WordListTemplate(
                    slug=slug,
                    icon=tpl_data["icon"],
                    title=tpl_data["title"],
                    description=tpl_data["description"],
                    category=tpl_data["category"],
                    sort_order=tpl_data["sort_order"],
                )
                db.add(tpl)
                db.flush()  # получаем id

                # Добавляем слова
                for position, headword in enumerate(tpl_data["words"]):
                    word_id = headword_to_id.get(headword)
                    if word_id is None:
                        # Слова нет в БКРС — пропускаем, шаблон останется,
                        # просто без этого слова
                        continue
                    db.add(WordListTemplateItem(
                        template_id=tpl.id,
                        word_id=word_id,
                        position=position,
                    ))
            else:
                # Шаблон уже есть — обновим только метаданные
                # (на случай если мы поменяли название/описание)
                existing.icon = tpl_data["icon"]
                existing.title = tpl_data["title"]
                existing.description = tpl_data["description"]
                existing.category = tpl_data["category"]
                existing.sort_order = tpl_data["sort_order"]

        db.commit()
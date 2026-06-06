"""
Pydantic-схемы — это контракт между API и клиентами.

Для чего они нужны:
  1. ВАЛИДАЦИЯ входных данных. Если клиент пришлёт мусор, Pydantic вернёт
     осмысленную ошибку 422 с описанием, ЧТО именно неправильно.
  2. СЕРИАЛИЗАЦИЯ выходных данных. SQLAlchemy-модели → JSON автоматически.
  3. ДОКУМЕНТАЦИЯ. FastAPI на основе схем сам генерирует Swagger UI.

Соглашение об именовании:
  - SomethingRead — то, что возвращаем клиенту (для GET-запросов)
  - SomethingCreate / SomethingUpdate — то, что принимаем от клиента
    (для POST / PUT) — пока не нужны, добавятся в будущих итерациях.
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# Базовые схемы
# ============================================================================

class ExampleRead(BaseModel):
    """Пример использования слова."""
    model_config = ConfigDict(from_attributes=True)

    chinese: str
    russian: Optional[str] = None


class MeaningRead(BaseModel):
    """Одно значение слова с примерами."""
    model_config = ConfigDict(from_attributes=True)

    position: int
    level: int
    translation: str
    examples: list[ExampleRead] = []


class LabelRead(BaseModel):
    """Помета (бот., мед., ист., ...)."""
    model_config = ConfigDict(from_attributes=True)

    name: str


class ReferenceRead(BaseModel):
    """Перекрёстная ссылка на другое слово."""
    model_config = ConfigDict(from_attributes=True)

    to_headword: str


# ============================================================================
# Схемы для эндпоинтов поиска
# ============================================================================

class SearchResultItem(BaseModel):
    """
    Краткая карточка слова в списке результатов поиска.

    Согласно нашему дизайну (Вариант А): здесь только то, что нужно
    отобразить в списке — иероглиф, пиньинь, первый перевод.
    Полная информация загружается отдельным запросом по /api/words/{id}.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Уникальный ID слова в БД")
    headword: str = Field(..., description="Иероглифическое написание")
    pinyin: Optional[str] = Field(None, description="Транскрипция пиньинь с тонами")
    short_translation: str = Field(
        ..., description="Первое значение, обрезанное до 100 символов"
    )
    category: str = Field(..., description="common | term | proper_noun | rare")
    hsk_level: Optional[int] = Field(None, ge=1, le=6, description="Уровень HSK 1-6")


class SearchResponse(BaseModel):
    """Ответ эндпоинта поиска: список + метаданные пагинации."""

    query: str = Field(..., description="Исходный запрос пользователя")
    total: int = Field(..., description="Общее количество найденных слов")
    limit: int = Field(..., description="Размер текущей страницы")
    offset: int = Field(..., description="Смещение от начала")
    items: list[SearchResultItem]
    elapsed_ms: float = Field(..., description="Время выполнения запроса в мс")


# ============================================================================
# Схема для эндпоинта /words/{id} — полная карточка
# ============================================================================

class WordDetail(BaseModel):
    """
    Полная карточка слова со всеми значениями, примерами, пометами и ссылками.
    Этот объект отображается, когда пользователь выбирает слово из списка.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    headword: str
    pinyin: Optional[str]
    pinyin_plain: Optional[str]
    category: str
    hsk_level: Optional[int]
    char_length: int
    meanings: list[MeaningRead]
    labels: list[LabelRead] = []
    references: list[ReferenceRead] = []


# ============================================================================
# Health check
# ============================================================================

class HealthResponse(BaseModel):
    """Ответ /api/health — простая проверка что сервер живой."""
    status: str = "ok"
    database: str = "connected"
    word_count: int


# ============================================================================
# Пользователи
# ============================================================================

# Допустимые значения цели (см. также models_users.VALID_GOALS).
# Дублируем здесь как Literal для строгой Pydantic-валидации входных данных.
from typing import Literal
GoalCode = Literal[
    "travel", "business", "culture", "study", "relocation", "hobby"
]


class UserRegister(BaseModel):
    """Данные для регистрации нового пользователя."""
    model_config = ConfigDict(from_attributes=True)

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_]+$",
        description="Логин (латиница, цифры, _; от 3 до 50 символов)",
        examples=["nadya123"],
    )
    display_name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Имя для отображения в приложении",
        examples=["Надя"],
    )
    level: Optional[int] = Field(
        None,
        ge=1,
        le=4,
        description="Уровень: 1=новичок, 2=HSK1-2, 3=HSK3-4, 4=HSK5-6; "
                    "null = пройти входной тест",
    )
    goals: list[GoalCode] = Field(
        default_factory=list,
        description="Цели изучения (можно несколько)",
        examples=[["travel", "culture"]],
    )


class UserLogin(BaseModel):
    """Данные для входа существующего пользователя."""
    username: str = Field(..., min_length=3, max_length=50)


class UserRead(BaseModel):
    """Полная информация о пользователе для возврата клиенту."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    level: Optional[int]
    goals: list[str]  # список goal-кодов
    created_at: str   # ISO datetime в строке для удобства мобильного клиента


class AuthResponse(BaseModel):
    """
    Ответ при регистрации/логине.

    В упрощённом MVP отдаём просто user_id и сам объект пользователя.
    Клиент сохраняет user_id локально и передаёт в заголовке X-User-Id
    при последующих запросах.

    В будущей версии (полноценная авторизация) здесь будет JWT-токен.
    """
    user_id: int
    user: UserRead


class UserUpdate(BaseModel):
    """Изменение профиля пользователя (для будущих эндпоинтов)."""
    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    level: Optional[int] = Field(None, ge=1, le=4)
    goals: Optional[list[GoalCode]] = None


# ============================================================================
# Иероглифы (этимология, декомпозиция, анимация написания)
# ============================================================================

class CharacterInfo(BaseModel):
    """
    Информация об одиночном иероглифе для блока "Структура" на карточке слова.
    
    Возвращается эндпоинтом GET /api/characters/{ch}
    """
    character: str = Field(..., description="Сам иероглиф")
    pinyin: list[str] = Field(default_factory=list, description="Возможные чтения")
    definition: Optional[str] = Field(None, description="Англоязычное определение")
    decomposition: Optional[str] = Field(
        None,
        description="Структура в нотации IDS (Ideographic Description Sequence)",
    )
    radical: Optional[str] = Field(None, description="Радикал (ключ)")
    etymology_type: Optional[str] = Field(
        None,
        description="Тип этимологии: pictographic / ideographic / pictophonetic",
    )
    etymology_hint: Optional[str] = Field(
        None,
        description="Текстовое описание происхождения иероглифа",
    )
    etymology_semantic: Optional[str] = Field(
        None, description="Семантическая часть (для pictophonetic)"
    )
    etymology_phonetic: Optional[str] = Field(
        None, description="Фонетическая часть (для pictophonetic)"
    )
    has_strokes: bool = Field(
        False,
        description="Доступны ли данные для анимации написания",
    )


class CharacterStrokes(BaseModel):
    """
    Данные SVG-штрихов для анимации написания.
    
    Возвращается эндпоинтом GET /api/characters/{ch}/strokes
    
    Клиент использует эти данные с библиотекой hanzi-writer.js,
    встроенной в WebView, для анимации написания иероглифа.
    """
    character: str
    strokes: list[str] = Field(..., description="SVG path-строки, по одной на черту")
    medians: list[list[list[int]]] = Field(
        ..., description="Координаты центральных линий штрихов для анимации"
    )


# ============================================================================
# Списки слов: системные шаблоны и пользовательские списки
# ============================================================================

class WordListTemplateRead(BaseModel):
    """Системный шаблон списка в каталоге."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    icon: Optional[str]
    title: str
    description: Optional[str]
    category: str
    word_count: int = Field(..., description="Сколько слов в этом шаблоне")


class UserListRead(BaseModel):
    """Краткая информация о пользовательском списке (для экрана 'Мои списки')."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    icon: Optional[str]
    word_count: int = Field(..., description="Сколько слов в списке")
    source_template_id: Optional[int] = Field(
        None,
        description="Если есть, список был создан из системного шаблона",
    )
    source_template_slug: Optional[str] = Field(
        None,
        description="Slug шаблона-источника (для UI)",
    )
    created_at: str


class UserListItemRead(BaseModel):
    """Одно слово в пользовательском списке (для экрана детали списка)."""
    model_config = ConfigDict(from_attributes=True)

    word_id: int
    position: int
    headword: str
    pinyin: Optional[str]
    first_translation: Optional[str]


class UserListDetail(BaseModel):
    """Подробности списка со всеми его словами."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    icon: Optional[str]
    source_template_id: Optional[int]
    created_at: str
    items: list[UserListItemRead]


class UserListCreate(BaseModel):
    """Создание пустого пользовательского списка с нуля."""
    title: str = Field(..., min_length=1, max_length=100)
    icon: Optional[str] = Field(None, max_length=8)


class UserListUpdate(BaseModel):
    """Переименование или смена иконки списка."""
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    icon: Optional[str] = Field(None, max_length=8)


class UserListSubscribe(BaseModel):
    """Подписка на системный шаблон — создаёт копию у пользователя."""
    template_id: int = Field(..., gt=0)
    # Можно опционально переопределить название копии
    custom_title: Optional[str] = Field(None, min_length=1, max_length=100)


class AddWordToListRequest(BaseModel):
    """Добавление слова в пользовательский список."""
    word_id: int = Field(..., gt=0)


# ============================================================================
# Прогресс изучения (тренажёр)
# ============================================================================

class ReviewAnswer(BaseModel):
    """
    Ответ пользователя на одно слово в тренировке.
    knows=True означает кнопка "Знаю", False — "Учу".
    """
    word_id: int = Field(..., gt=0)
    knows: bool


class ProgressItem(BaseModel):
    """Прогресс по одному конкретному слову (для статистики)."""
    model_config = ConfigDict(from_attributes=True)

    word_id: int
    times_seen: int
    times_known: int
    streak: int
    is_learned: bool
    last_reviewed_at: Optional[str] = None


class TrainerCard(BaseModel):
    """
    Одна карточка в режиме тренировки — слово + его прогресс.

    Возвращается из эндпоинта подготовки сессии: серверу удобнее одним
    запросом отдать готовые карточки, чем заставлять клиент собирать их
    из двух источников (слово + прогресс).
    """
    word_id: int
    headword: str
    pinyin: Optional[str]
    translation: Optional[str]
    is_learned: bool
    times_seen: int


class TrainerSession(BaseModel):
    """Готовый сет карточек для тренировки по списку."""
    list_id: int
    list_title: str
    cards: list[TrainerCard]


class ProgressStats(BaseModel):
    """Сводка по всему прогрессу пользователя (для главного экрана)."""
    total_seen: int = Field(..., description="Сколько уникальных слов видел")
    total_learned: int = Field(..., description="Сколько отмечено как выученные")
    total_reviews: int = Field(..., description="Сколько всего тренировок-ответов")


# ============================================================================
# Входное тестирование уровня (HSK)
# ============================================================================

class TestQuestion(BaseModel):
    """
    Один вопрос входного теста.

    Три типа вопросов (поле question_type):

      "choose_translation" — показывается иероглиф + пиньинь, нужно выбрать
                             правильный перевод из 4 вариантов.
                             Поле choices содержит 4 варианта (включая правильный).

      "choose_hanzi"       — показывается перевод, нужно выбрать иероглиф из 4.
                             choices — массив иероглифов.

      "type_translation"   — показывается иероглиф + пиньинь, нужно ввести
                             перевод текстом. choices = пустой массив.
                             Поле accepted_answers содержит все приемлемые
                             ответы для проверки.
    """
    question_type: str = Field(..., description="choose_translation | choose_hanzi | type_translation")
    word_id: int
    hanzi: str = Field(..., description="Иероглифы слова")
    pinyin: Optional[str]
    correct_answer: str = Field(..., description="Правильный ответ (текст)")
    choices: list[str] = Field(default_factory=list, description="4 варианта для multiple choice")
    accepted_answers: list[str] = Field(
        default_factory=list,
        description="Все приемлемые ответы для type_translation (lowercase)",
    )


class TestQuestionBatch(BaseModel):
    """Пакет вопросов одного HSK уровня."""
    hsk_level: int
    questions: list[TestQuestion]


class LevelTestResultRequest(BaseModel):
    """Результат теста — финальный уровень и статистика."""
    determined_level: int = Field(..., ge=1, le=6, description="HSK 1-6")
    answers_per_level: dict[str, list[int]] = Field(
        ...,
        description=(
            "Ключ — HSK уровень в виде строки '1','2'.. "
            "Значение — [правильных, всего] на этом уровне"
        ),
    )


class LevelTestResultResponse(BaseModel):
    """Ответ после сохранения результата."""
    determined_hsk_level: int
    app_level: int = Field(..., description="Уровень в шкале приложения (1-4)")
    saved: bool = Field(..., description="Сохранён ли уровень в профиле")
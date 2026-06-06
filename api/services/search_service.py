"""
Бизнес-логика поиска.

Отделение service-слоя от routers — это паттерн "Layered Architecture":
  - routers/ знают про HTTP, валидируют входные данные, возвращают JSON
  - services/ ничего не знают про HTTP — они работают с данными и БД
  - models/ ничего не знают ни про HTTP, ни про логику — только структура

Это даёт огромные плюсы:
  - Логику можно переиспользовать (например, в фоновых задачах, CLI-командах)
  - Легко тестировать service-слой без HTTP
  - Легко в будущем поменять FastAPI на gRPC, не трогая бизнес-логику
"""
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class SearchResultRow:
    """DTO для результата поиска (без зависимости от ORM или Pydantic)."""
    id: int
    headword: str
    pinyin: str | None
    short_translation: str
    category: str
    hsk_level: int | None


@dataclass
class SearchResult:
    """Результат поиска целиком: данные + метаданные."""
    items: list[SearchResultRow]
    total: int
    elapsed_ms: float


def _detect_query_type(query: str) -> str:
    """
    Определяет тип поискового запроса по символам:
      - "chinese"  — есть китайские иероглифы
      - "russian"  — кириллица
      - "pinyin"   — латиница (пиньинь)

    Тип определяет, какой алгоритм ранжирования применить.
    """
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in query)
    has_cyrillic = any(
        'а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in query
    )
    if has_chinese:
        return "chinese"
    if has_cyrillic:
        return "russian"
    return "pinyin"


# =========================================================================
# SQL-запросы для разных типов запросов.
#
# Используем text() — сырой SQL — потому что FTS5 не поддерживается
# напрямую в SQLAlchemy ORM. Это нормально: запросы параметризованы,
# защита от SQL-инъекций есть.
#
# Параметры в text() передаются через :name, не через "?" — это синтаксис
# именно SQLAlchemy.
# =========================================================================

# Поиск по иероглифу — стандартный FTS5 ранкинг работает отлично
_SQL_SEARCH_CHINESE = text("""
    SELECT 
        w.id,
        w.headword,
        w.pinyin,
        w.category,
        w.hsk_level,
        (SELECT translation FROM meanings 
         WHERE word_id = w.id AND position = 1 LIMIT 1) AS short_translation
    FROM words_fts
    JOIN words w ON w.id = words_fts.rowid
    WHERE words_fts MATCH :query
        AND (:category IS NULL OR w.category = :category)
        AND (:hsk IS NULL OR w.hsk_level = :hsk)
    ORDER BY rank
    LIMIT :limit OFFSET :offset
""")

# Поиск по русскому — умное ранжирование с приоритетом основной лексики
_SQL_SEARCH_RUSSIAN = text("""
    SELECT 
        w.id,
        w.headword,
        w.pinyin,
        w.category,
        w.hsk_level,
        m.translation AS short_translation
    FROM words_fts
    JOIN words w ON w.id = words_fts.rowid
    LEFT JOIN meanings m ON m.word_id = w.id AND m.position = 1
    WHERE words_fts MATCH :query
        AND (:category IS NULL OR w.category = :category)
        AND (:hsk IS NULL OR w.hsk_level = :hsk)
    ORDER BY 
        CASE 
            WHEN m.translation LIKE :exact_prefix THEN 0
            WHEN m.translation LIKE :exact_substring THEN 1
            ELSE 2 
        END,
        CASE w.category
            WHEN 'common' THEN 0
            WHEN 'term' THEN 1
            WHEN 'proper_noun' THEN 2
            WHEN 'rare' THEN 3
        END,
        w.char_length ASC,
        rank
    LIMIT :limit OFFSET :offset
""")

# Поиск по пиньинь
_SQL_SEARCH_PINYIN = text("""
    SELECT 
        w.id,
        w.headword,
        w.pinyin,
        w.category,
        w.hsk_level,
        (SELECT translation FROM meanings 
         WHERE word_id = w.id AND position = 1 LIMIT 1) AS short_translation
    FROM words_fts
    JOIN words w ON w.id = words_fts.rowid
    WHERE words_fts MATCH :query
        AND (:category IS NULL OR w.category = :category)
        AND (:hsk IS NULL OR w.hsk_level = :hsk)
    ORDER BY 
        CASE w.category WHEN 'common' THEN 0 ELSE 1 END,
        w.char_length ASC,
        rank
    LIMIT :limit OFFSET :offset
""")

# Подсчёт ВСЕГО результатов для пагинации
_SQL_COUNT = text("""
    SELECT COUNT(*) FROM words_fts
    JOIN words w ON w.id = words_fts.rowid
    WHERE words_fts MATCH :query
        AND (:category IS NULL OR w.category = :category)
        AND (:hsk IS NULL OR w.hsk_level = :hsk)
""")


# Максимально допустимое смещение пагинации.
# Защищаемся от запросов с offset=999999999 — SQLite такие запросы тянет долго.
MAX_OFFSET = 1000


def _normalize_short_translation(translation: str | None, max_length: int = 100) -> str:
    """Обрезаем длинные переводы для отображения в списке результатов."""
    if not translation:
        return ""
    if len(translation) <= max_length:
        return translation
    return translation[:max_length].rstrip() + "…"


def _build_fts_query(query: str) -> str:
    """
    Подготавливает запрос для передачи в FTS5.

    FTS5 имеет специальные символы: " * ( ) AND OR NOT — их нужно экранировать,
    иначе пользовательский ввод может сломать запрос.

    Самый простой способ — обернуть весь запрос в двойные кавычки и удвоить
    кавычки внутри (FTS5 escaping).

    Также сохраняем поддержку префикса "слово*" для пользователей, которые
    знают синтаксис FTS5 — но проверяем, что звёздочка только в конце.
    """
    query = query.strip()
    if not query:
        return ""

    # Простой случай: пользователь явно использовал префиксный поиск
    # типа "xue*" — отдаём как есть (без кавычек, FTS поймёт).
    if query.endswith("*") and query.count("*") == 1 and '"' not in query:
        prefix = query[:-1]
        # Экранируем кавычки в префиксе
        safe_prefix = prefix.replace('"', '""')
        return f'"{safe_prefix}"*'

    # Обычный случай: оборачиваем в кавычки, экранируя кавычки внутри.
    # FTS5 трактует это как фразовый запрос — найдёт точные вхождения.
    safe = query.replace('"', '""')
    return f'"{safe}"'


def search_words(
    db: Session,
    query: str,
    limit: int,
    offset: int,
    category: str | None = None,
    hsk_level: int | None = None,
) -> SearchResult:
    """
    Главная функция поиска. Маршрутизирует запрос в нужный SQL в зависимости
    от типа ввода и возвращает результаты.
    """
    # Защита от слишком глубокой пагинации
    if offset > MAX_OFFSET:
        offset = MAX_OFFSET

    fts_query = _build_fts_query(query)
    if not fts_query:
        return SearchResult(items=[], total=0, elapsed_ms=0.0)

    query_type = _detect_query_type(query)
    start = time.perf_counter()

    params = {
        "query": fts_query,
        "limit": limit,
        "offset": offset,
        "category": category,
        "hsk": hsk_level,
    }

    try:
        # Получаем total (для пагинации UI)
        total = db.execute(_SQL_COUNT, params).scalar() or 0

        # Получаем сами результаты по нужному алгоритму ранжирования
        if query_type == "chinese":
            sql = _SQL_SEARCH_CHINESE
        elif query_type == "russian":
            sql = _SQL_SEARCH_RUSSIAN
            # Доп. параметры для умного ранжирования по русскому
            params["exact_prefix"] = f"{query}%"
            params["exact_substring"] = f"%{query}%"
        else:  # pinyin
            sql = _SQL_SEARCH_PINYIN

        rows = db.execute(sql, params).all()
    except Exception as e:
        # Если FTS5 не понял запрос (бывает при странных символах) — 
        # возвращаем пустой результат, не падаем.
        # В реальном проекте здесь должно быть логирование.
        print(f"[search] Ошибка FTS5: {e}")
        return SearchResult(items=[], total=0, elapsed_ms=0.0)

    items = [
        SearchResultRow(
            id=row.id,
            headword=row.headword,
            pinyin=row.pinyin,
            short_translation=_normalize_short_translation(row.short_translation),
            category=row.category,
            hsk_level=row.hsk_level,
        )
        for row in rows
    ]

    elapsed_ms = (time.perf_counter() - start) * 1000
    return SearchResult(items=items, total=total, elapsed_ms=elapsed_ms)

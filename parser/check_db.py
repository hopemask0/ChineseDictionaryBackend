"""
Интерактивная диагностика БД словаря.

Запуск:
    python check_db.py [запрос]
    python check_db.py [запрос] --all   # без умного ранкинга, все результаты

Без аргументов — выводит общую статистику.

Алгоритм умного ранжирования для русского запроса:
  1. Точное совпадение в начале перевода — выше частичного
  2. Категории: common > term > proper_noun > rare
  3. Короткие слова — обычно базовая лексика, выше длинных словосочетаний
"""

import sqlite3
import sys
import time
from pathlib import Path

DB_FILE = Path(r"D:\study\diplomchik\backend\data\bkrs.db")


def show_stats(conn: sqlite3.Connection) -> None:
    """Общая статистика БД."""
    cur = conn.cursor()
    print("=" * 60)
    print(f"📊 Статистика БД: {DB_FILE}")
    print(f"   Размер: {DB_FILE.stat().st_size / 1024 / 1024:.1f} МБ")
    print("=" * 60)

    tables = [
        ('words', 'Слов'),
        ('meanings', 'Значений'),
        ('examples', 'Примеров'),
        ('labels', 'Помет (уникальных)'),
        ('word_labels', 'Пометы у слов'),
        ('word_references', 'Перекрёстных ссылок'),
    ]
    for table, label in tables:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"   {label:25} {cur.fetchone()[0]:>10,}")

    print("\n   Распределение по категориям:")
    cur.execute(
        "SELECT category, COUNT(*) FROM words GROUP BY category ORDER BY 2 DESC"
    )
    for cat, cnt in cur.fetchall():
        print(f"     {cat:15} {cnt:>10,}")

    print("\n   Топ-10 помет:")
    cur.execute("""
        SELECT l.name, COUNT(*) as cnt 
        FROM labels l JOIN word_labels wl ON wl.label_id = l.id 
        GROUP BY l.id ORDER BY cnt DESC LIMIT 10
    """)
    for name, cnt in cur.fetchall():
        print(f"     {name:15} {cnt:>10,}")

    # Случайные слова с примерами
    print("\n   Случайные слова с примерами:")
    cur.execute("""
        SELECT w.headword, w.pinyin, m.translation, e.chinese, e.russian
        FROM examples e
        JOIN meanings m ON m.id = e.meaning_id
        JOIN words w ON w.id = m.word_id
        ORDER BY RANDOM()
        LIMIT 3
    """)
    for hw, py, tr, cn, ru in cur.fetchall():
        print(f"\n     🈁 {hw} [{py or '—'}]")
        print(f"        {tr[:80]}")
        print(f"        ► {cn}")
        print(f"        ► {ru}")


def search_word(conn: sqlite3.Connection, query: str, show_all: bool = False) -> None:
    """Полнотекстовый поиск с умным ранжированием."""
    cur = conn.cursor()
    start = time.perf_counter()

    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in query)
    has_cyrillic = any('а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in query)

    if has_chinese:
        # По иероглифу: стандартный FTS5 rank работает отлично
        cur.execute("""
            SELECT w.id, w.headword, w.pinyin, w.category, w.hsk_level
            FROM words_fts
            JOIN words w ON w.id = words_fts.rowid
            WHERE words_fts MATCH ?
            ORDER BY rank
            LIMIT 10
        """, (query,))
    elif has_cyrillic and not show_all:
        # По русскому: приоритет коротких "основных" слов
        cur.execute("""
            SELECT w.id, w.headword, w.pinyin, w.category, w.hsk_level
            FROM words_fts
            JOIN words w ON w.id = words_fts.rowid
            LEFT JOIN meanings m ON m.word_id = w.id AND m.position = 1
            WHERE words_fts MATCH ?
            ORDER BY 
                CASE 
                    WHEN m.translation LIKE ? || '%' THEN 0
                    WHEN m.translation LIKE '%' || ? || '%' THEN 1
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
            LIMIT 10
        """, (query, query, query))
    else:
        # Пиньинь или показать все
        cur.execute("""
            SELECT w.id, w.headword, w.pinyin, w.category, w.hsk_level
            FROM words_fts
            JOIN words w ON w.id = words_fts.rowid
            WHERE words_fts MATCH ?
            ORDER BY 
                CASE w.category WHEN 'common' THEN 0 ELSE 1 END,
                w.char_length ASC,
                rank
            LIMIT 10
        """, (query,))

    rows = cur.fetchall()
    elapsed = (time.perf_counter() - start) * 1000

    print(f"\n🔍 Запрос: '{query}'")
    print(f"   Найдено: {len(rows)} результат(ов) за {elapsed:.1f} мс\n")

    for row in rows:
        word_id, hw, py, cat, hsk = row[0], row[1], row[2], row[3], row[4]
        hsk_str = f" HSK{hsk}" if hsk else ""
        print(f"  📖 {hw}  [{py or '—'}]  ({cat}{hsk_str})")

        cur.execute(
            "SELECT translation FROM meanings WHERE word_id = ? ORDER BY position",
            (word_id,)
        )
        for (tr,) in cur.fetchall():
            print(f"     • {tr[:120]}")

        cur.execute("""
            SELECT e.chinese, e.russian 
            FROM examples e 
            JOIN meanings m ON m.id = e.meaning_id 
            WHERE m.word_id = ? 
            LIMIT 2
        """, (word_id,))
        for cn, ru in cur.fetchall():
            print(f"     ► {cn}")
            print(f"       {ru}")
        print()


def main():
    if not DB_FILE.exists():
        print(f"❌ БД не найдена: {DB_FILE}")
        print("   Сначала запусти load_to_sqlite.py")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_FILE))
    conn.execute("PRAGMA query_only = ON")

    try:
        args = [a for a in sys.argv[1:] if a != '--all']
        show_all = '--all' in sys.argv[1:]

        if args:
            query = ' '.join(args)
            search_word(conn, query, show_all=show_all)
        else:
            show_stats(conn)
    finally:
        conn.close()


if __name__ == '__main__':
    main()

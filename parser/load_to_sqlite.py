"""
Загружает разобранный словарь БКРС из JSON в SQLite.

Версия 2: упрощённый и надёжный алгоритм.
Главное отличие от v1: всё делается за ОДИН проход по JSON.
Слова, значения, примеры и FTS вставляются вместе, в одной транзакции.
Это исключает рассинхронизацию между таблицами.

Запуск:
    python load_to_sqlite.py
"""

import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Iterator
from tqdm import tqdm


# Пути — поправь под себя
DATA_DIR = Path(r"D:\study\diplomchik\backend\data")
JSON_FILE = DATA_DIR / "bkrs_full.json"
DB_FILE = DATA_DIR / "bkrs.db"
SCHEMA_FILE = Path(__file__).parent / "schema.sql"

# Размер пакета для коммита. Большой коммит = быстрее, но выше пик памяти.
COMMIT_EVERY = 10000


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def strip_pinyin_tones(pinyin: str) -> str:
    """'nǐ hǎo' → 'nihao'. Убираем диакритику и пробелы."""
    if not pinyin:
        return ""
    decomposed = unicodedata.normalize('NFD', pinyin)
    no_diacritics = ''.join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r'\s+', '', no_diacritics).lower()


def char_length(text: str) -> int:
    """Количество китайских иероглифов в строке."""
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')


_PROPER_NOUN_HINTS = re.compile(
    r'\b(фамилия|имя|город|посёлок|посел|пров\.|провинция|штат|остров|'
    r'река|оз\.|озеро|г\.|пос\.|уезд|округ|деревня|село|гора|пик)\b',
    re.IGNORECASE
)

_TERM_LABELS = {
    'бот.', 'мед.', 'хим.', 'физ.', 'биол.', 'мат.', 'тех.', 'техн.',
    'зоол.', 'анат.', 'юр.', 'комп.', 'эл.', 'геогр.', 'геол.', 'астр.',
    'лингв.', 'грам.', 'муз.', 'астрол.', 'спорт.', 'воен.', 'эк.',
    'фин.', 'архит.', 'фарм.', 'физиол.', 'псих.', 'филос.', 'лог.',
    'миф.', 'кит. мед.', 'хим.-ан.', 'микол.', 'этн.',
}


def classify_category(translation: str, labels: list[str]) -> str:
    """Определяет категорию слова на основе помет и текста перевода."""
    if set(labels) & _TERM_LABELS:
        return 'term'
    if _PROPER_NOUN_HINTS.search(translation):
        return 'proper_noun'
    if len(translation) > 80 and '(' not in translation and ',' not in translation:
        return 'rare'
    return 'common'


def stream_json_entries(filepath: Path) -> Iterator[dict]:
    """Потоковое чтение JSON-массива (ожидаем формат с записями построчно)."""
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip().rstrip(',')
            if line in ('[', ']', ''):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"⚠️  Пропускаю битую строку JSON: {e}")
                continue


# ---------------------------------------------------------------------------
# Загрузка
# ---------------------------------------------------------------------------

def init_database(db_path: Path, schema_path: Path) -> sqlite3.Connection:
    """Создаёт БД с нуля по схеме."""
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -128000")  # 128 МБ кэш

    with open(schema_path, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())

    return conn


def load_data(conn: sqlite3.Connection, json_file: Path) -> dict:
    """
    Один проход по JSON. Для каждой статьи:
      1. INSERT в words → получаем word_id
      2. INSERT в meanings (с привязкой к word_id) → получаем meaning_id
      3. INSERT в examples (с привязкой к meaning_id)
      4. INSERT в word_labels, word_references, words_fts

    Никаких "буферов на потом" — всё сразу.
    """
    cur = conn.cursor()
    label_cache: dict[str, int] = {}
    seen_headwords: set[str] = set()  # для отслеживания дубликатов

    stats = {
        'words': 0, 'meanings': 0, 'examples': 0,
        'labels_used': 0, 'references': 0,
        'category_common': 0, 'category_proper_noun': 0,
        'category_term': 0, 'category_rare': 0,
        'no_pinyin': 0, 'duplicates': 0,
    }

    def get_or_create_label(name: str) -> int:
        """Кэшированное получение id пометы."""
        if name in label_cache:
            return label_cache[name]
        cur.execute("INSERT OR IGNORE INTO labels(name) VALUES (?)", (name,))
        cur.execute("SELECT id FROM labels WHERE name = ?", (name,))
        label_id = cur.fetchone()[0]
        label_cache[name] = label_id
        return label_id

    print(f"\n📥 Загружаем данные из {json_file.name}...\n")

    with tqdm(unit=" слов", unit_scale=True) as pbar:
        for entry in stream_json_entries(json_file):
            headword = entry['headword']

            # Дубликат? Пропускаем целиком (вместе с meanings/examples)
            if headword in seen_headwords:
                stats['duplicates'] += 1
                pbar.update(1)
                continue
            seen_headwords.add(headword)

            pinyin = entry.get('pinyin')
            pinyin_plain = strip_pinyin_tones(pinyin) if pinyin else None

            # Объединённый текст всех переводов — для FTS и классификации
            all_translations = ' | '.join(
                m['text'] for m in entry.get('meanings', []) if m.get('text')
            )
            category = classify_category(
                all_translations, entry.get('all_labels', [])
            )

            stats[f'category_{category}'] += 1
            if not pinyin:
                stats['no_pinyin'] += 1

            # 1) Вставляем СЛОВО
            cur.execute(
                "INSERT INTO words "
                "(headword, pinyin, pinyin_plain, category, char_length) "
                "VALUES (?, ?, ?, ?, ?)",
                (headword, pinyin, pinyin_plain, category, char_length(headword))
            )
            word_id = cur.lastrowid
            stats['words'] += 1

            # 2) Вставляем ЗНАЧЕНИЯ + ПРИМЕРЫ
            for position, meaning in enumerate(entry.get('meanings', []), start=1):
                cur.execute(
                    "INSERT INTO meanings "
                    "(word_id, position, level, translation) "
                    "VALUES (?, ?, ?, ?)",
                    (word_id, position, meaning.get('level', 1),
                     meaning.get('text', ''))
                )
                meaning_id = cur.lastrowid
                stats['meanings'] += 1

                # Примеры этого значения
                for ex in meaning.get('examples', []):
                    cur.execute(
                        "INSERT INTO examples (meaning_id, chinese, russian) "
                        "VALUES (?, ?, ?)",
                        (meaning_id, ex.get('chinese', ''), ex.get('russian', ''))
                    )
                    stats['examples'] += 1

                # Ссылки на другие слова из этого значения
                for ref in meaning.get('references', []):
                    cur.execute(
                        "INSERT OR IGNORE INTO word_references "
                        "(from_word_id, to_headword) VALUES (?, ?)",
                        (word_id, ref)
                    )
                    stats['references'] += 1

            # 3) Вставляем ПОМЕТЫ
            for label in entry.get('all_labels', []):
                label_id = get_or_create_label(label)
                cur.execute(
                    "INSERT OR IGNORE INTO word_labels (word_id, label_id) "
                    "VALUES (?, ?)",
                    (word_id, label_id)
                )

            # 4) Вставляем в FTS-индекс
            cur.execute(
                "INSERT INTO words_fts "
                "(rowid, headword, pinyin, pinyin_plain, translations) "
                "VALUES (?, ?, ?, ?, ?)",
                (word_id, headword, pinyin or '', pinyin_plain or '',
                 all_translations)
            )

            pbar.update(1)

            # Периодический коммит, чтобы транзакция не разрасталась
            if stats['words'] % COMMIT_EVERY == 0:
                conn.commit()

        conn.commit()

    # Метаданные
    cur.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ('source', 'BKRS DSL 2025-09-20')
    )
    cur.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ('loaded_at', time.strftime('%Y-%m-%d %H:%M:%S'))
    )
    cur.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        ('word_count', str(stats['words']))
    )
    conn.commit()

    stats['labels_used'] = len(label_cache)
    return stats


def main():
    if not JSON_FILE.exists():
        raise FileNotFoundError(
            f"Не найден {JSON_FILE}. Сначала запусти merge_to_json.py"
        )
    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(f"Не найдена схема {SCHEMA_FILE}")

    print(f"Источник:  {JSON_FILE}")
    print(f"Назначение: {DB_FILE}")

    start = time.perf_counter()
    conn = init_database(DB_FILE, SCHEMA_FILE)

    try:
        stats = load_data(conn, JSON_FILE)

        # Финальная оптимизация: ANALYZE обновляет статистику для оптимизатора
        # запросов, чтобы он использовал правильные индексы.
        conn.commit()
        print("\n🔧 Запускаем ANALYZE...")
        conn.execute("ANALYZE")
        conn.commit()

        # Возвращаем безопасный режим
        conn.execute("PRAGMA synchronous = FULL")
    finally:
        conn.close()

    elapsed = time.perf_counter() - start
    db_size_mb = DB_FILE.stat().st_size / (1024 * 1024)

    print(f"\n{'=' * 60}")
    print(f"✅ Загрузка завершена за {elapsed:.1f} сек")
    print(f"   Размер БД: {db_size_mb:.1f} МБ\n")
    print(f"   Слов:           {stats['words']:>12,}")
    print(f"   Значений:       {stats['meanings']:>12,}")
    print(f"   Примеров:       {stats['examples']:>12,}")
    print(f"   Помет:          {stats['labels_used']:>12,}")
    print(f"   Ссылок:         {stats['references']:>12,}")
    print(f"   Без пиньинь:    {stats['no_pinyin']:>12,}")
    print(f"   Дубликатов:     {stats['duplicates']:>12,}\n")
    print(f"   Категории:")
    print(f"     общая лексика:    {stats['category_common']:>12,}")
    print(f"     имена собств.:    {stats['category_proper_noun']:>12,}")
    print(f"     термины:          {stats['category_term']:>12,}")
    print(f"     редкое:           {stats['category_rare']:>12,}")


if __name__ == '__main__':
    main()

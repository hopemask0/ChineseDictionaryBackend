"""
Переразметка категорий и уровней HSK в словаре БКРС.

Что делает:
  1. Загружает HSK 2.0 (классические уровни 1-6) и HSK 3.0 (расширенный common)
  2. Перебирает все слова в bkrs.db
  3. Переразмечает category и hsk_level по правилам:

Правила переразметки (от высшего приоритета к низшему):

  a) Слово в HSK 2.0 → category='common', hsk_level=<маппинг 1-6 на 1-4>
     - HSK 1-2 (old-1, old-2)  → app_level=2 (HSK 1-2)
     - HSK 3-4 (old-3, old-4)  → app_level=3 (HSK 3-4)
     - HSK 5-6 (old-5, old-6)  → app_level=4 (HSK 5-6)

  b) Слово в HSK 3.0 (но не в 2.0) → category='common', hsk_level=NULL
     Это полезные слова, но без классического уровня

  c) Имя собственное (по эвристике) → category='proper_noun'

  d) "Редкая форма" (перевод "вм. X" / "см. X" в виде ссылки) → category='rare'

  e) Иначе → category='rare' (более строго чем раньше)
     Если слово не входит ни в один HSK и не имеет других маркеров,
     для пользователя оно скорее редкое.

Использование:
    python remark_categories.py path/to/bkrs.db path/to/complete.json [--dry-run]
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path


# ========== Маппинг уровней ==========
# Наше приложение использует level 1..4 (см. domain/model/User.kt::Level):
#   1 = BEGINNER (новичок)
#   2 = HSK 1-2 (базовый)
#   3 = HSK 3-4 (средний)
#   4 = HSK 5-6 (продвинутый)
#
# HSK 2.0 имеет 6 уровней. Маппим попарно:
HSK_OLD_TO_APP_LEVEL = {
    'old-1': 2,  # HSK 1 → "HSK 1-2"
    'old-2': 2,
    'old-3': 3,
    'old-4': 3,
    'old-5': 4,
    'old-6': 4,
}


# ========== Эвристики для имён собственных ==========
# Сильные сигналы — если найден один из этих маркеров, точно proper_noun,
# даже если слово есть в HSK списке (например, 北京 в HSK 1).
STRONG_PROPER_NOUN_MARKERS = [
    'имя собств',
    '(имя)', '(фамилия)',
    'геогр.', 'геогр,', ' геогр ',
    'герой фильма', 'персонаж романа', 'персонаж фильма',
    'династия', 'император', 'императрица',
]

# Слабые сигналы — указывают на возможное имя собственное,
# но проверяем только если слово НЕ в HSK
WEAK_PROPER_NOUN_KEYWORDS = [
    'город', 'провинция', 'район', 'округ', 'уезд',
    'река', 'озеро', 'гора', 'хребет', 'остров', 'море',
    'фамилия', 'богиня', 'бог ',
    'страна', 'королевство', 'империя', 'республика',
    'персонаж', 'роман',
]


def has_strong_proper_noun_marker(translation: str) -> bool:
    """Сильные маркеры имени собственного — переопределяют HSK."""
    if not translation:
        return False
    t_lower = translation.lower()
    return any(m in t_lower for m in STRONG_PROPER_NOUN_MARKERS)


def is_likely_proper_noun(translation: str, pinyin: str | None) -> bool:
    """
    Эвристика: похоже ли слово на имя собственное?
    
    Признаки:
      1. Перевод содержит характерные слова (см. STRONG/WEAK)
      2. Pinyin начинается с большой буквы (стандартная конвенция китайской
         типографики для имён собственных: Běi jīng, не běi jīng)
    """
    if not translation:
        return False

    t_lower = translation.lower()
    if any(kw in t_lower for kw in STRONG_PROPER_NOUN_MARKERS):
        return True
    if any(kw in t_lower for kw in WEAK_PROPER_NOUN_KEYWORDS):
        return True

    # Pinyin с заглавной буквы — сильный признак имени собственного
    if pinyin and pinyin[0].isupper():
        return True

    return False


def is_rare_form(translation: str) -> bool:
    """
    Проверка: это редкая форма-ссылка?
    
    Типичные шаблоны:
      "вм. 鸟"     — вариант написания (вместо)
      "см. 茑"     — смотри (синоним)
      "тоже что 学" — то же что
    
    Такие записи — это варианты других иероглифов, не самостоятельные слова.
    """
    if not translation:
        return False

    t = translation.strip().lower()
    # Очень короткие переводы вида "вм. X" / "см. X"
    if len(t) < 30:
        if re.match(r'^(вм\.|см\.|то\s?же\s+что|тоже\s+что)', t):
            return True

    return False


def load_hsk_data(json_path: Path) -> tuple[dict[str, int], set[str]]:
    """
    Загружает HSK-данные и возвращает:
      hsk_level_map: {слово -> app_level (1-4)}  — только из HSK 2.0
      common_set: множество всех слов из HSK 2.0 + 3.0
    """
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)

    hsk_level_map: dict[str, int] = {}
    common_set: set[str] = set()

    for entry in data:
        word = entry.get('simplified', '')
        if not word:
            continue

        # Всё что есть в любом HSK — это common
        common_set.add(word)

        # Если есть OLD уровень — берём минимальный (самый базовый)
        levels = entry.get('level', [])
        old_levels = [HSK_OLD_TO_APP_LEVEL[lvl] for lvl in levels if lvl in HSK_OLD_TO_APP_LEVEL]
        if old_levels:
            min_app_level = min(old_levels)
            # Если слово встречается в нескольких old-уровнях, оставляем минимальный
            current = hsk_level_map.get(word)
            if current is None or min_app_level < current:
                hsk_level_map[word] = min_app_level

    return hsk_level_map, common_set


def determine_category_and_level(
    headword: str,
    pinyin: str | None,
    first_translation: str | None,
    hsk_map: dict[str, int],
    common_set: set[str],
) -> tuple[str, int | None]:
    """
    Определяет (category, hsk_level) для одного слова.
    
    Приоритеты:
      1. СИЛЬНЫЙ маркер имени собственного → 'proper_noun'
         (даже если слово в HSK — "имя собств." в переводе важнее)
      2. Слово целиком в HSK 2.0 → 'common' с уровнем
      3. Слово целиком в HSK 3.0 → 'common' без уровня
      4. Все иероглифы слова есть в HSK 3.0 → 'common' без уровня
         (для составных слов типа 你好, которых нет как лексической единицы,
          но все компоненты в common)
      5. СЛАБАЯ эвристика имени собственного → 'proper_noun'
      6. Редкая форма-ссылка → 'rare'
      7. По дефолту → 'rare'
    
    Возвращает: (category, hsk_level_or_None)
    """
    translation = first_translation or ''

    # Приоритет 1: сильный маркер имени собственного — переопределяет HSK
    if has_strong_proper_noun_marker(translation):
        return 'proper_noun', None

    # Приоритет 2: HSK 2.0 — точный матч слова
    if headword in hsk_map:
        return 'common', hsk_map[headword]

    # Приоритет 3: HSK 3.0 — точный матч слова
    if headword in common_set:
        return 'common', None

    # Приоритет 4: все иероглифы слова есть в HSK 3.0 (для коротких составных)
    # Применяем только к словам длиной 2-3 иероглифа, иначе будет ложноположительно
    # для длинных терминов вида "социалистический реализм".
    if 2 <= len(headword) <= 3:
        if all(ch in common_set for ch in headword):
            return 'common', None

    # Приоритет 5: слабая эвристика имени собственного
    if is_likely_proper_noun(translation, pinyin):
        return 'proper_noun', None

    # Приоритет 6: редкая форма-ссылка
    if is_rare_form(translation):
        return 'rare', None

    # Дефолт: rare. Это более строго чем раньше, но соответствует факту —
    # если слова нет ни в одном HSK и оно не имеет других маркеров,
    # для среднего пользователя оно действительно редкое.
    return 'rare', None


def remark_database(db_path: Path, hsk_json: Path, dry_run: bool = False) -> None:
    """
    Главная функция переразметки.
    """
    print(f"📚 Загружаю HSK-данные из {hsk_json}")
    hsk_map, common_set = load_hsk_data(hsk_json)
    print(f"   HSK 2.0 (с уровнями): {len(hsk_map)} слов")
    print(f"   HSK 3.0 (всего common): {len(common_set)} слов")

    print(f"\n📖 Открываю {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Сначала считаем сколько всего слов в БД
    total = cursor.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    print(f"   Всего слов в БД: {total}")

    # Статистика ДО
    print("\n📊 СТАТИСТИКА ДО:")
    for row in cursor.execute(
        "SELECT category, COUNT(*) as cnt FROM words GROUP BY category ORDER BY cnt DESC"
    ):
        pct = row['cnt'] / total * 100
        print(f"   {row['category']:<15} {row['cnt']:>10}  ({pct:.1f}%)")

    print(f"\n🔍 Перебираю все слова...")

    # Итерируемся по всем словам с первым переводом
    # Используем LEFT JOIN, чтобы не пропустить слова без переводов
    query = """
        SELECT w.id, w.headword, w.pinyin,
               (SELECT translation FROM meanings 
                WHERE word_id = w.id AND position = 1 LIMIT 1) AS first_translation
        FROM words w
    """

    # Собираем обновления батчами для производительности
    updates: list[tuple[str, int | None, int]] = []  # (category, hsk_level, word_id)
    stats = {
        'common_hsk_old': 0,
        'common_hsk_new': 0,
        'proper_noun': 0,
        'rare_form': 0,
        'rare_default': 0,
    }

    processed = 0
    for row in cursor.execute(query):
        processed += 1
        if processed % 100000 == 0:
            print(f"   Обработано {processed}/{total}...")

        category, hsk_level = determine_category_and_level(
            headword=row['headword'],
            pinyin=row['pinyin'],
            first_translation=row['first_translation'],
            hsk_map=hsk_map,
            common_set=common_set,
        )

        # Сбор статистики
        if category == 'common' and hsk_level is not None:
            stats['common_hsk_old'] += 1
        elif category == 'common' and hsk_level is None:
            stats['common_hsk_new'] += 1
        elif category == 'proper_noun':
            stats['proper_noun'] += 1
        elif category == 'rare':
            # Отличаем "редкую форму" от "редкого по дефолту"
            if is_rare_form(row['first_translation'] or ''):
                stats['rare_form'] += 1
            else:
                stats['rare_default'] += 1

        updates.append((category, hsk_level, row['id']))

    print(f"   Готово, всего обработано: {processed}")

    print("\n📊 СТАТИСТИКА ПОСЛЕ (по правилам переразметки):")
    print(f"   common (HSK 2.0, с уровнем) {stats['common_hsk_old']:>10}")
    print(f"   common (HSK 3.0, без уровня){stats['common_hsk_new']:>10}")
    print(f"   proper_noun (имя собств.)   {stats['proper_noun']:>10}")
    print(f"   rare (форма-ссылка)         {stats['rare_form']:>10}")
    print(f"   rare (по дефолту)           {stats['rare_default']:>10}")

    if dry_run:
        print("\n🔬 DRY-RUN режим: изменения НЕ применяются")
        print("   Уберите --dry-run для реальной записи в БД")
        conn.close()
        return

    print(f"\n💾 Применяю обновления в БД ({len(updates)} записей)...")

    # Делаем batch-update пачками по 5000 для производительности
    BATCH = 5000
    for i in range(0, len(updates), BATCH):
        batch = updates[i:i + BATCH]
        cursor.executemany(
            "UPDATE words SET category = ?, hsk_level = ? WHERE id = ?",
            batch,
        )
        if (i // BATCH) % 20 == 0 and i > 0:
            print(f"   Применено {i}/{len(updates)}...")

    conn.commit()
    print(f"   Применено всё: {len(updates)} обновлений")

    # Финальная проверка
    print("\n✅ ФИНАЛЬНОЕ СОСТОЯНИЕ БД:")
    for row in cursor.execute(
        "SELECT category, COUNT(*) as cnt FROM words GROUP BY category ORDER BY cnt DESC"
    ):
        pct = row['cnt'] / total * 100
        print(f"   {row['category']:<15} {row['cnt']:>10}  ({pct:.1f}%)")

    print("\n📊 Распределение по HSK уровням (только common):")
    for row in cursor.execute("""
        SELECT hsk_level, COUNT(*) as cnt 
        FROM words 
        WHERE category = 'common'
        GROUP BY hsk_level
        ORDER BY hsk_level NULLS LAST
    """):
        lvl = row['hsk_level'] if row['hsk_level'] is not None else 'NULL'
        print(f"   level={lvl:<5} {row['cnt']:>10}")

    conn.close()
    print("\n🎉 Готово!")


def main():
    parser = argparse.ArgumentParser(
        description="Переразметка категорий и уровней HSK в словаре БКРС"
    )
    parser.add_argument('db_path', type=Path, help='Путь к bkrs.db')
    parser.add_argument('hsk_json', type=Path, help='Путь к complete.json (HSK vocabulary)')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Только показать статистику, не записывать в БД',
    )
    args = parser.parse_args()

    if not args.db_path.exists():
        print(f"❌ БД не найдена: {args.db_path}", file=sys.stderr)
        sys.exit(1)
    if not args.hsk_json.exists():
        print(f"❌ HSK-файл не найден: {args.hsk_json}", file=sys.stderr)
        sys.exit(1)

    remark_database(args.db_path, args.hsk_json, dry_run=args.dry_run)


if __name__ == '__main__':
    main()

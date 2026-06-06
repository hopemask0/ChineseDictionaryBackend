"""
Объединяет три DSL-файла БКРС в один JSON-файл.

Промежуточный шаг между DSL и SQLite. JSON удобен тем, что:
  - его можно открыть и проверить глазами
  - легко загрузить в любую БД (SQLite, PostgreSQL, MongoDB)
  - на этапе отладки можно заново перезагружать БД без перепарсинга

Запуск:
    python merge_to_json.py
"""

import json
import time
from pathlib import Path
from tqdm import tqdm

from bkrs_parser import parse_dsl_file


# Пути настраивай под себя. У тебя на диске D:\
DSL_DIR = Path(r"D:\study\diplomchik\dsl_dabkrs_250920")
OUTPUT_DIR = Path(r"D:\study\diplomchik\backend\data")

DSL_FILES = [
    DSL_DIR / "dabkrs_1.dsl",
    DSL_DIR / "dabkrs_2.dsl",
    DSL_DIR / "dabkrs_3.dsl",
]

OUTPUT_FILE = OUTPUT_DIR / "bkrs_full.json"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Сразу проверяем, что все файлы на месте — не хочется упасть после 30 минут работы
    for f in DSL_FILES:
        if not f.exists():
            raise FileNotFoundError(f"Не найден файл: {f}")

    print(f"Будет обработано {len(DSL_FILES)} файлов")
    print(f"Результат: {OUTPUT_FILE}\n")

    start = time.perf_counter()
    total_count = 0
    seen_headwords: dict[str, int] = {}  # для подсчёта дубликатов между файлами

    # Пишем JSON-массив построчно (потоково), чтобы не держать всё в памяти
    # Формат: JSON-массив, но каждая запись на своей строке (JSONL-стиль внутри [])
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as out:
        out.write('[\n')
        first_entry = True

        for dsl_file in DSL_FILES:
            print(f"\n📖 Парсим {dsl_file.name}...")
            file_count = 0

            # tqdm для прогресс-бара. unit_scale=True красиво показывает 'k', 'M'
            iterator = parse_dsl_file(str(dsl_file))
            with tqdm(iterator, desc=dsl_file.name, unit=" статей",
                      unit_scale=True) as pbar:
                for entry in pbar:
                    # Считаем дубликаты (одно слово в разных файлах = редко, но бывает)
                    seen_headwords[entry.headword] = seen_headwords.get(entry.headword, 0) + 1

                    if not first_entry:
                        out.write(',\n')
                    json.dump(entry.to_dict(), out, ensure_ascii=False)
                    first_entry = False

                    file_count += 1
                    total_count += 1

            print(f"   Готово: {file_count:,} статей")

        out.write('\n]\n')

    elapsed = time.perf_counter() - start

    # Статистика
    duplicates = sum(1 for c in seen_headwords.values() if c > 1)
    file_size_mb = OUTPUT_FILE.stat().st_size / (1024 * 1024)

    print(f"\n{'=' * 50}")
    print(f"✅ Готово!")
    print(f"   Всего статей:    {total_count:,}")
    print(f"   Уникальных слов: {len(seen_headwords):,}")
    print(f"   Дубликатов:      {duplicates:,}")
    print(f"   Размер файла:    {file_size_mb:.1f} МБ")
    print(f"   Время:           {elapsed:.1f} сек")


if __name__ == '__main__':
    main()

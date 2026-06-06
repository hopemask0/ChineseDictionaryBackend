"""
Парсер DSL-файлов БКРС (Большого китайско-русского словаря).

Преобразует исходный DSL-формат в структурированные Python-объекты,
готовые для загрузки в реляционную БД.

Структура DSL-статьи:
    заголовок_слова          ← без отступа в начале строки
     пиньинь                  ← один пробел в начале (или '_' если нет)
     [m1]перевод[/m]           ← один пробел в начале

Файл начинается со служебных заголовков (#NAME, #INDEX_LANGUAGE и т.д.),
которые мы пропускаем.
"""

import re
from dataclasses import dataclass, field, asdict
from typing import Iterator, Optional


# ---------------------------------------------------------------------------
# Структуры данных
# ---------------------------------------------------------------------------

@dataclass
class Example:
    """Пример использования слова: китайский текст + русский перевод."""
    chinese: str
    russian: str


@dataclass
class Meaning:
    """Одно значение слова (у слова может быть несколько значений)."""
    # Уровень отступа в исходнике (m1=1, m2=2, m3=3) — для отладки
    level: int
    # Чистый текст перевода (без DSL-тегов)
    text: str
    # Пометы — например, ['бот.', 'мед.']
    labels: list[str] = field(default_factory=list)
    # Примеры использования для этого значения
    examples: list[Example] = field(default_factory=list)
    # Ссылки на другие слова (тег [ref])
    references: list[str] = field(default_factory=list)


@dataclass
class DictEntry:
    """Полная словарная статья."""
    headword: str  # Иероглиф (само слово)
    pinyin: Optional[str]  # Транскрипция или None если в DSL стоит '_'
    meanings: list[Meaning] = field(default_factory=list)
    # Все пометы со всех значений (для удобной фильтрации)
    all_labels: list[str] = field(default_factory=list)
    # Сырой DSL-текст всей статьи (для отладки и на случай если что-то упустили)
    raw_body: str = ""

    def to_dict(self) -> dict:
        """Преобразует в словарь для сериализации в JSON."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Извлечение тегов из DSL
# ---------------------------------------------------------------------------

# Регулярка для примеров: [ex]китайский русский[/ex]
_EX_RE = re.compile(r'\[ex\](.*?)\[/ex\]', re.DOTALL)

# Регулярка для помет: [p]бот.[/p]
_P_RE = re.compile(r'\[p\](.*?)\[/p\]')

# Регулярка для ссылок: [ref]другое_слово[/ref]
_REF_RE = re.compile(r'\[ref\](.*?)\[/ref\]')

# Регулярка для удаления ВСЕХ DSL-тегов (когда нужен чистый текст)
_TAG_RE = re.compile(r'\[/?[a-zA-Z*]+\d*\]')


def _split_example(ex_text: str) -> Example:
    """
    Пример в DSL: '刺桐港是世界巨港之一 порт Цытун является одним из крупнейших...'
    Китайский и русский текст разделены пробелом, но точную границу
    определить сложно. Используем простую эвристику: ищем первый
    нелатинский→латинский переход.
    """
    ex_text = ex_text.strip()
    # Ищем первую кириллическую/латинскую букву после китайских символов
    chinese_part = []
    russian_start = 0
    for i, ch in enumerate(ex_text):
        # Китайские иероглифы и пунктуация
        if '\u4e00' <= ch <= '\u9fff' or ch in '，。！？；：、""''（）《》【】':
            chinese_part.append(ch)
            russian_start = i + 1
        elif ch.isspace() and chinese_part:
            # Пробел после китайского — возможно, начался русский
            # Проверяем следующий значимый символ
            rest = ex_text[i + 1:].lstrip()
            if rest and not ('\u4e00' <= rest[0] <= '\u9fff'):
                russian_start = i + 1
                break
            chinese_part.append(ch)
        else:
            # Не-китайский символ
            if chinese_part:
                russian_start = i
                break

    chinese = ex_text[:russian_start].strip()
    russian = ex_text[russian_start:].strip()
    # Если разделить не удалось — возвращаем всё в chinese
    if not russian:
        return Example(chinese=chinese, russian="")
    return Example(chinese=chinese, russian=russian)


def _strip_tags(text: str) -> str:
    """Удаляет все DSL-теги, оставляет чистый текст."""
    text = _TAG_RE.sub('', text)
    # Убираем лишние пробелы
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _parse_meanings(body: str) -> list[Meaning]:
    """
    Разбирает строку body (всё кроме заголовка и пиньинь) на отдельные значения.

    Основной формат: значения в DSL ограничены тегами [m1]...[/m], [m2]...[/m] и т.д.
    Цифра после m — уровень отступа.

    Запасной формат: иногда статьи приходят без [m]-обёртки (~0.01% статей в БКРС).
    Тогда трактуем всё тело как одно значение.
    """
    meanings: list[Meaning] = []

    # Ищем все блоки [m\d]...[/m]
    pattern = re.compile(r'\[m(\d)\](.*?)\[/m\]', re.DOTALL)

    for match in pattern.finditer(body):
        level = int(match.group(1))
        content = match.group(2)

        # Извлекаем примеры до удаления тегов
        examples = []
        for ex_match in _EX_RE.finditer(content):
            examples.append(_split_example(ex_match.group(1)))

        # Извлекаем пометы
        labels = [_strip_tags(p).strip() for p in _P_RE.findall(content)]
        labels = [lbl for lbl in labels if lbl]  # убираем пустые

        # Извлекаем ссылки
        references = [_strip_tags(r).strip() for r in _REF_RE.findall(content)]
        references = [r for r in references if r]

        # Удаляем теги примеров и [*]...[/*] из основного текста перевода
        clean_content = _EX_RE.sub('', content)
        clean_content = re.sub(r'\[\*\].*?\[/\*\]', '', clean_content, flags=re.DOTALL)
        clean_text = _strip_tags(clean_content)

        if clean_text or examples or references:
            meanings.append(Meaning(
                level=level,
                text=clean_text,
                labels=labels,
                examples=examples,
                references=references,
            ))

    # Запасной вариант: если в теле нет [m]-блоков, но есть какой-то текст
    if not meanings and body.strip():
        clean_text = _strip_tags(body)
        # Убираем экранированные квадратные скобки, оставшиеся от \[ \]
        clean_text = clean_text.replace('\\[', '[').replace('\\]', ']').strip()
        if clean_text:
            meanings.append(Meaning(level=1, text=clean_text))

    return meanings


# ---------------------------------------------------------------------------
# Чтение DSL-файла
# ---------------------------------------------------------------------------

def parse_dsl_file(filepath: str) -> Iterator[DictEntry]:
    """
    Генератор словарных статей из DSL-файла.

    Используем генератор, а не список, потому что файл большой
    и мы не хотим держать все 1+ млн записей в памяти одновременно.

    Алгоритм построчного парсинга:
      - Если строка начинается с # → служебный заголовок, пропускаем.
      - Если строка пустая → разделитель, пропускаем.
      - Если строка не начинается с пробела/таба → это новый headword.
        Перед ним надо отдать накопленную статью (если была).
      - Если строка начинается с пробела/таба → это содержимое статьи.
    """
    current_headword: Optional[str] = None
    current_lines: list[str] = []

    # Открываем файл с правильной кодировкой UTF-16 LE
    with open(filepath, 'r', encoding='utf-16-le') as f:
        # Пропускаем BOM-метку, если она есть
        first_char = f.read(1)
        if first_char != '\ufeff':
            f.seek(0)

        for line in f:
            # Убираем перевод строки (но НЕ начальные пробелы — они важны)
            line = line.rstrip('\r\n')

            # Пустая строка — разделитель
            if not line.strip():
                continue

            # Служебный заголовок
            if line.startswith('#'):
                continue

            # Новая статья начинается со строки БЕЗ начального пробела
            if not line.startswith(' ') and not line.startswith('\t'):
                # Если у нас уже есть накопленная статья — отдаём её
                if current_headword is not None:
                    entry = _build_entry(current_headword, current_lines)
                    if entry is not None:
                        yield entry
                # Начинаем новую статью
                current_headword = line.strip()
                current_lines = []
            else:
                # Это строка с содержимым — добавляем к текущей статье
                current_lines.append(line.strip())

        # Последняя статья в файле
        if current_headword is not None:
            entry = _build_entry(current_headword, current_lines)
            if entry is not None:
                yield entry


def _merge_example_only_meanings(meanings: list[Meaning]) -> list[Meaning]:
    """
    Объединяет значения, содержащие ТОЛЬКО примеры (без текста перевода),
    с предыдущим значением.

    В DSL примеры часто оформляются как отдельный [m3]-блок:
        [m1]слово[/m]
        [m2]1) первое значение[/m]
        [m3][*][ex]пример[/ex][/*][/m]   ← только пример, без перевода
        [m2]2) второе значение[/m]

    Пользователю удобнее видеть пример рядом со значением, а не отдельной записью.
    """
    if not meanings:
        return meanings

    result = [meanings[0]]
    for m in meanings[1:]:
        # Если у значения нет текста, но есть примеры — присоединяем к предыдущему
        if not m.text and (m.examples or m.references):
            result[-1].examples.extend(m.examples)
            result[-1].references.extend(m.references)
        else:
            result.append(m)
    return result


def _build_entry(headword: str, body_lines: list[str]) -> Optional[DictEntry]:
    """Собирает DictEntry из заголовка и накопленных строк тела статьи."""
    if not body_lines:
        return None

    # Первая строка — пиньинь (может быть '_' если отсутствует)
    pinyin_line = body_lines[0]
    if pinyin_line == '_':
        pinyin = None
    else:
        # Убираем теги [b]...[/b] из пиньинь, если есть
        pinyin = _strip_tags(pinyin_line)

    # Остальные строки — тело со значениями
    body = ' '.join(body_lines[1:])

    meanings = _parse_meanings(body)
    meanings = _merge_example_only_meanings(meanings)

    # Собираем все уникальные пометы со всех значений
    all_labels = []
    seen = set()
    for m in meanings:
        for lbl in m.labels:
            if lbl not in seen:
                all_labels.append(lbl)
                seen.add(lbl)

    return DictEntry(
        headword=headword,
        pinyin=pinyin,
        meanings=meanings,
        all_labels=all_labels,
        raw_body=body[:500],  # сохраняем первые 500 символов для отладки
    )


# ---------------------------------------------------------------------------
# CLI для быстрой проверки
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys
    import json

    if len(sys.argv) < 2:
        print("Использование: python bkrs_parser.py <путь_к_dsl> [количество_статей]")
        sys.exit(1)

    filepath = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    print(f"Парсим первые {limit} статей из {filepath}...\n")

    for i, entry in enumerate(parse_dsl_file(filepath)):
        if i >= limit:
            break
        print(f"=== Статья #{i + 1} ===")
        print(json.dumps(entry.to_dict(), ensure_ascii=False, indent=2))
        print()

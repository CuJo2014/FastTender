"""Парсер CSV/TSV.

Автоматически определяет кодировку (через chardet) и разделитель (csv.Sniffer
с резервной эвристикой для tab/semicolon, которые Sniffer плохо распознаёт
на русскоязычных файлах с CP1251).
"""

import csv
from io import StringIO
from pathlib import Path

import chardet

from fasttender.services.parser._matrix import build_result
from fasttender.services.parser.types import ColumnMapping, ParseError, ParseResult

# Кандидаты разделителей для эвристики, если csv.Sniffer не справился
_CANDIDATE_DELIMITERS = (",", ";", "\t", "|")


def parse_csv(
    path: Path,
    *,
    mapping_override: ColumnMapping | None = None,
    encoding_override: str | None = None,
    delimiter_override: str | None = None,
) -> ParseResult:
    """Парсит CSV/TSV-файл."""
    raw = path.read_bytes()
    if not raw:
        raise ParseError("CSV-файл пуст", details={"path": str(path)})

    encoding = encoding_override or _detect_encoding(raw)
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as exc:
        # chardet ошибся — пробуем cp1251 как самый частый для русских файлов
        if encoding != "cp1251":
            try:
                text = raw.decode("cp1251")
                encoding = "cp1251"
            except UnicodeDecodeError:
                raise ParseError(
                    f"Не удалось декодировать файл: {exc}",
                    details={"detected_encoding": encoding},
                ) from exc
        else:
            raise ParseError(
                f"Не удалось декодировать файл: {exc}",
                details={"detected_encoding": encoding},
            ) from exc

    # BOM убираем явно — utf-8-sig делает это, но текст у нас уже декодирован
    if text.startswith("﻿"):
        text = text[1:]

    delimiter = delimiter_override or _detect_delimiter(text)

    reader = csv.reader(StringIO(text), delimiter=delimiter)
    matrix = [list(row) for row in reader]

    if not matrix:
        raise ParseError("CSV-файл не содержит строк после разбора")

    return build_result(
        matrix,
        sheet_name=None,
        encoding=encoding,
        delimiter=delimiter,
        mapping_override=mapping_override,
    )


def _detect_encoding(raw: bytes) -> str:
    """Определяет кодировку через chardet, с дефолтом utf-8."""
    # Анализируем не больше первых 100 KB — этого хватит для уверенного детекта
    sample = raw[: 100 * 1024]
    result = chardet.detect(sample)
    encoding = result.get("encoding") or "utf-8"
    confidence = result.get("confidence") or 0.0

    # chardet иногда возвращает MacCyrillic/KOI8-R с низкой уверенностью —
    # для нашего домена (русский B2B) более вероятна cp1251
    if confidence < 0.6 and encoding.lower() in {"maccyrillic", "koi8-r", "iso-8859-5"}:
        encoding = "cp1251"

    # utf-8-sig эквивалентен utf-8 + BOM; декодер сам разберётся
    if encoding.lower() == "ascii":
        encoding = "utf-8"

    # Нормализуем алиасы к каноническим именам Python-кодеков
    aliases = {
        "windows-1251": "cp1251",
        "windows-1252": "cp1252",
        "iso-8859-1": "latin1",
    }
    normalized = encoding.lower()
    return aliases.get(normalized, normalized)


def _detect_delimiter(text: str) -> str:
    """Определяет разделитель CSV.

    Сначала пытаемся csv.Sniffer на первых ~10 строках; если не удалось —
    эвристика «какой кандидат даёт самое стабильное число колонок».
    """
    sample = "\n".join(text.splitlines()[:10])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(_CANDIDATE_DELIMITERS))
        return dialect.delimiter
    except csv.Error:
        pass

    # Эвристика: для каждого кандидата считаем число колонок по строкам;
    # выбираем тот, у которого медиана > 1 и разброс минимален.
    best: tuple[int, int, str] = (0, 99, ",")  # (median_cols, variance, delimiter)
    for d in _CANDIDATE_DELIMITERS:
        cols_per_row = [len(line.split(d)) for line in text.splitlines()[:20] if line]
        if not cols_per_row:
            continue
        median = sorted(cols_per_row)[len(cols_per_row) // 2]
        if median < 2:
            continue
        variance = max(cols_per_row) - min(cols_per_row)
        if median > best[0] or (median == best[0] and variance < best[1]):
            best = (median, variance, d)

    return best[2]

"""Проигрывание записанного лога вместо живой шины.

Позволяет проверить весь путь — кадр, событие, решение автомата — не имея
ни машины, ни кабеля. Логи лежат в logs/ и сняты с настоящей машины.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from ibus import Frame

HEX_BYTE = re.compile(r"^[0-9A-Fa-f]{2}$")


def frames_from_log(path: Path) -> Iterator[Frame]:
    """Кадры из лога снифера.

    Строка выглядит так:
        37.714  F0 04 68 48 30 E4        BMBT → RAD    48 30  кнопка...
    Берём подряд идущие шестнадцатеричные байты после метки времени и
    останавливаемся на первом нешестнадцатеричном слове — дальше идёт разбор,
    а не сам кадр. Строки, которые не разобрались, молча пропускаем:
    в логе есть и заголовки, и итоговая строка со счётчиком.
    """
    for line in path.read_text(encoding="utf-8").splitlines():
        tokens = line.split()
        if len(tokens) < 2:
            continue
        raw: list[int] = []
        for token in tokens[1:]:
            if not HEX_BYTE.match(token):
                break
            raw.append(int(token, 16))
        if len(raw) < 5:
            continue
        try:
            yield Frame.parse(bytes(raw))
        except ValueError:
            continue

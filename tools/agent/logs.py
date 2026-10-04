"""Журнал работы.

Пишем в файл, а не полагаемся на journald: у пользовательских служб он на этой
системе не сохраняется, и после перезагрузки выяснять причину было бы нечем.
А выяснять придётся в гараже, где под рукой только телефон.

Файлы лежат в ~/logi/ и сами подрезаются, чтобы карта не переполнилась.
Одновременно всё печатается в stdout, так что при ручном запуске видно то же
самое.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(os.environ.get("BMW_LOG_DIR", Path.home() / "logi"))
MAX_BYTES = 5 * 1024 * 1024
KEEP = 3

# Время с миллисекундами: на шине события идут плотно, и без них порядок
# восстановить невозможно.
FORMAT = "%(asctime)s %(levelname)-7s %(name)-8s %(message)s"
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup(name: str, *, verbose: bool = False) -> logging.Logger:
    """Журнал с записью в ~/logi/<name>.log и выводом на экран."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    formatter = logging.Formatter(FORMAT, TIME_FORMAT)
    formatter.default_msec_format = "%s.%03d"

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_DIR / f"{name}.log", maxBytes=MAX_BYTES, backupCount=KEEP, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as exc:
        # Некуда писать — это неприятно, но не повод не работать.
        logger.warning("журнал в файл недоступен: %s", exc)

    return logger

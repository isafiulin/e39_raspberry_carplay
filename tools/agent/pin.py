"""Вывод HOLD на GPIO26: держит ключ 12 В на плате из docs/20.

После подачи питания HOLD = 1 ставит сама прошивка по строке
`gpio=26=op,dh` в config.txt, ещё до Linux. Здесь его только отпускают
и возвращают. Утилита pinctrl есть в Raspberry Pi OS и выставляет вывод
насовсем, без процесса, который его держит.
"""

from __future__ import annotations

import logging
import subprocess

HOLD_GPIO = 26


class PinctrlHold:
    def __init__(self, log: logging.Logger, gpio: int = HOLD_GPIO) -> None:
        self.log = log
        self.gpio = gpio

    def set(self, on: bool) -> None:
        level = "dh" if on else "dl"
        subprocess.run(["pinctrl", "set", str(self.gpio), "op", level], check=True)


class LogHold:
    """Для стенда без платы: только пишет в журнал, что сделал бы."""

    def __init__(self, log: logging.Logger) -> None:
        self.log = log

    def set(self, on: bool) -> None:
        self.log.info("HOLD = %d (вывод не трогаю, управление питанием выключено)", int(on))

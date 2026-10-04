"""Смысловые события из кадров шины.

`decode.py` делает человекочитаемые подписи для глаз. Здесь — то же самое,
но для программы: структуры, по которым можно принимать решения.

Все коды кнопок и разбор состояний сняты с живой машины 30.09.2026,
логи и разбор лежат в logs/. Там же сказано, чего мы ещё не знаем.
"""

from __future__ import annotations

from dataclasses import dataclass

from .frame import Frame

# --- кнопки монитора, команда 0x48 -------------------------------------------
# К коду кнопки прибавляется 0x00 при нажатии, 0x40 при удержании, 0x80 при
# отпускании. Проверено: 30 и B0 для DISPLAY, 23 и A3 для MODE, 34 и B4 для MENU.
BUTTON_COMMAND = 0x48
# Кнопка SELECT выпадает из общего ряда: у неё своя команда 0x47 и лишний
# нулевой байт перед кодом. Снято с машины 01.10.2026 — в опубликованной
# таблице BMBT её нет вовсе, и мы её сначала сочли «немой».
SELECT_COMMAND = 0x47
SELECT_BUTTONS = {0x0F: "select"}
ACTION_MASK = 0b1100_0000
CODE_MASK = 0b0011_1111
ACTIONS = {0x00: "нажата", 0x40: "удержание", 0x80: "отпущена"}

# Проверено на этой машине 30.09.2026: mode, display, menu, select.
# Остальное — из опубликованной таблицы BMBT, она сходится с нашими замерами
# по всем четырём пунктам, поэтому доверия ей больше, чем обычному форуму.
# https://github.com/piersholt/wilhelm-docs/blob/master/bmbt/48.md
BUTTONS = {
    0x00: "vpravo",   # правая стрелка нижней пары
    0x10: "vlevo",    # левая стрелка нижней пары
    0x04: "tone",     # в шину ничего не шлёт, монитор обрабатывает сам
    0x05: "dial",     # нажатие правой крутилки, уходит в GT
    0x06: "power",    # кнопка ручки громкости
    0x07: "chasy",    # кнопка с часами
    0x14: "dvoynaya", # двойная стрелка, одна кнопка
    0x23: "mode",
    0x30: "display",  # в таблице называется Overlay
    0x34: "menu",
}

# --- крутилка, команда 0x49 ---------------------------------------------------
DIAL_COMMAND = 0x49
DIAL_RIGHT_BIT = 0b1000_0000
DIAL_STEPS_MASK = 0b0001_1111

# --- прочее -------------------------------------------------------------------
MONITOR_COMMAND = 0x4F
# Команда монитора радио про звук. Её он шлёт в довесок к видеокоманде,
# когда владелец входит в Television через меню: 01 — звук забирает ТВ,
# 00 — отдаёт обратно. Снято с машины 30.09.2026.
AUDIO_COMMAND = 0x4E
IGNITION_COMMAND = 0x11
SPEED_COMMAND = 0x18
GEAR_COMMAND = 0x13
RADIO_TEXT_PREFIX = (0x23, 0x62)

IGNITION = {0x00: "выключено", 0x01: "Kl.R", 0x03: "Kl.15", 0x07: "стартер"}

# Значения передачи в кадре 80 0A BF 13 00 XX. Видели четыре, за полноту
# списка не ручаемся: снято наблюдением, а не по документации.
GEARS = {0x11: "R", 0x71: "N", 0x81: "D", 0x83: "D", 0xB1: "P"}


@dataclass(frozen=True)
class Button:
    """Кнопка монитора. `name` может быть None, если код нам незнаком."""

    code: int
    action: str
    name: str | None

    @property
    def pressed(self) -> bool:
        return self.action == "нажата"

    def __str__(self) -> str:
        return f"кнопка {self.name or f'код {self.code:02X}'}: {self.action}"


@dataclass(frozen=True)
class Dial:
    """Поворот правой крутилки."""

    right: bool
    steps: int

    def __str__(self) -> str:
        return f"крутилка: {'вправо' if self.right else 'влево'} на {self.steps}"


@dataclass(frozen=True)
class RadioText:
    """Строка, которую радио вывело на экран. Так оно сообщает источник."""

    text: str

    def __str__(self) -> str:
        return f"радио на экране: {self.text!r}"


@dataclass(frozen=True)
class MonitorState:
    """Состояние монитора из кадра ED → BMBT."""

    raw: tuple[int, int]

    @property
    def showing_av(self) -> bool:
        """Модуль показывает именно наш вход AV, а не камеру.

        Второй байт говорит, что именно модуль выводит: 0b10 это вход AV,
        0b01 это камера или отсутствие своего видео. Различать важно: при
        задней передаче экран тоже занят модулем, но CarPlay там не видно.
        """
        return self.video_module_owns_screen and self.raw[1] & 0b11 == 0b10

    @property
    def video_module_owns_screen(self) -> bool:
        """Экран занят видеомодулем, а не навигацией.

        Первый байт: 0x11 когда показывает модуль, 0x12 когда экран у GT.
        """
        return self.raw[0] & 0b11 == 0b01

    def __str__(self) -> str:
        who = "видеомодуль" if self.video_module_owns_screen else "навигация"
        return f"экран занят: {who}"


@dataclass(frozen=True)
class AudioToTv:
    """Монитор распорядился звуком: забрал себе или вернул."""

    taken: bool

    def __str__(self) -> str:
        return "звук забрал ТВ" if self.taken else "звук вернулся радио"


@dataclass(frozen=True)
class Steering:
    """Кнопка на руле.

    ВНИМАНИЕ: коды взяты из таблицы сообщества, а не с этой машины — нажатий
    руля в наших логах нет. Проверить первым же снифером в гараже.
    """

    name: str | None
    action: str

    @property
    def pressed(self) -> bool:
        return self.action == "нажата"

    def __str__(self) -> str:
        return f"руль: {self.name or '?'}, {self.action}"


@dataclass(frozen=True)
class Ignition:
    state: str

    def __str__(self) -> str:
        return f"зажигание: {self.state}"


@dataclass(frozen=True)
class Speed:
    kmh: int
    rpm: int

    def __str__(self) -> str:
        return f"скорость {self.kmh} км/ч, обороты {self.rpm}"


@dataclass(frozen=True)
class Gear:
    """Положение селектора. `name` может быть None для незнакомого значения."""

    code: int
    name: str | None

    def __str__(self) -> str:
        return f"передача: {self.name or f'код {self.code:02X}'}"


# --- кнопки руля, адрес 0x50 --------------------------------------------------
# Коды из таблицы сообщества, на этой машине не проверены.
MFL_ADDRESS = 0x50
MFL_COMMAND = 0x3B
MFL_BUTTON_MASK = 0b1100_1001
MFL_STATE_MASK = 0b0011_0000
MFL_BUTTONS = {0x01: "вперёд", 0x08: "назад", 0x40: "R/T", 0x80: "телефон"}
MFL_STATES = {0x00: "нажата", 0x10: "удержание", 0x20: "отпущена"}

Event = Button | Dial | RadioText | MonitorState | Ignition | Speed | Gear | Steering | AudioToTv


def _text(data: bytes) -> str:
    return "".join(chr(b) for b in data if 0x20 <= b < 0x7F).strip()


def event(frame: Frame) -> Event | None:
    """Смысловое событие из кадра, либо None если кадр нам неинтересен."""
    data = frame.data
    if not data:
        return None

    if data[0] == BUTTON_COMMAND and len(data) >= 2:
        raw = data[1]
        action = ACTIONS.get(raw & ACTION_MASK)
        if action is None:
            return None
        code = raw & CODE_MASK
        return Button(code=code, action=action, name=BUTTONS.get(code))

    if data[0] == SELECT_COMMAND and len(data) >= 3:
        raw = data[2]
        action = ACTIONS.get(raw & ACTION_MASK)
        if action is None:
            return None
        code = raw & CODE_MASK
        return Button(code=code, action=action, name=SELECT_BUTTONS.get(code))

    if data[0] == DIAL_COMMAND and len(data) >= 2:
        raw = data[1]
        return Dial(right=bool(raw & DIAL_RIGHT_BIT), steps=raw & DIAL_STEPS_MASK)

    if data[0] == AUDIO_COMMAND and len(data) >= 2:
        return AudioToTv(taken=data[1] == 0x01)

    if data[0] == MONITOR_COMMAND and frame.dst == 0xF0 and len(data) >= 3:
        return MonitorState(raw=(data[1], data[2]))

    if frame.src == MFL_ADDRESS and data[0] == MFL_COMMAND and len(data) >= 2:
        value = data[1]
        return Steering(
            name=MFL_BUTTONS.get(value & MFL_BUTTON_MASK),
            action=MFL_STATES.get(value & MFL_STATE_MASK, "состояние ?"),
        )

    if frame.src == 0x80:
        if data[0] == IGNITION_COMMAND and len(data) >= 2:
            return Ignition(state=IGNITION.get(data[1], f"код {data[1]:02X}"))
        if data[0] == SPEED_COMMAND and len(data) >= 3:
            return Speed(kmh=data[1], rpm=data[2] * 100)
        if data[0] == GEAR_COMMAND and len(data) >= 3:
            return Gear(code=data[2], name=GEARS.get(data[2]))

    if len(data) >= 4 and (data[0], data[1]) == RADIO_TEXT_PREFIX:
        return RadioText(text=_text(data[3:]))

    return None

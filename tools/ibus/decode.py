"""Расшифровка знакомых сообщений в человеческий текст.

Коды сверены с документацией сообщества piersholt/wilhelm-docs, ссылки
указаны у каждой группы. Это всё равно не официальная документация BMW:
перед тем как закладывать код в прошивку, подтвердите его снифером на
своей машине. Всё неопознанное возвращается как None, и снифер печатает
сырые байты.
"""

from __future__ import annotations

from .frame import Frame

# --- CD-чейнджер, адрес 0x18 -------------------------------------------------

CDC_REQUEST = {
    0x01: "опрос: ты здесь?",
    0x38: "команда чейнджеру",
}

CDC_COMMAND = {
    0x00: "статус",
    0x01: "стоп",
    0x02: "пауза",
    0x03: "играть",
    0x04: "быстрая перемотка",
    0x05: "смена трека",
    0x06: "смена диска",
    0x07: "сканирование",
    0x08: "случайный порядок",
    0x0A: "следующий или предыдущий трек",
}

# Статус чейнджера 0x39: после байта команды идут
# Status | Function | Error | Magazine | Aux | Disc | Track
# https://github.com/piersholt/wilhelm-docs/blob/master/cdc/39.md
CDC_STATUS_DISC = 6
CDC_STATUS_TRACK = 7
CDC_STATUS_MIN_LEN = 8

# --- Управление монитором, команда 0x4F --------------------------------------

BMBT_SOURCE = {0b00: "навигация", 0b01: "TV", 0b10: "видео GT"}
# Младшие два бита второго байта раньше читались как формат видео (NTSC/PAL).
# Наблюдения в машине 30.09.2026 это опровергли: биты меняются при включении
# задней передачи, то есть следуют за тем, что модуль показывает, а не за
# стандартом сигнала. Видели только два значения, поэтому подписываем осторожно.
BMBT_OUTPUT = {0b01: "вход камеры или нет своего видео", 0b10: "вход AV или TV"}
BMBT_ASPECT = {0b0000: "4:3", 0b0001: "16:9", 0b0011: "zoom"}

# --- Кнопки руля, адрес 0x50 -------------------------------------------------
# https://github.com/piersholt/wilhelm-docs/blob/master/mfl/3b.md
MFL_BUTTON_MASK = 0b1100_1001
MFL_BUTTON = {0x01: "вперёд", 0x08: "назад", 0x40: "R/T", 0x80: "телефон"}
MFL_STATE_MASK = 0b0011_0000
MFL_STATE = {0x00: "нажата", 0x10: "удержание", 0x20: "отпущена"}

# --- Крутилка монитора, команда 0x49 -----------------------------------------
# https://github.com/piersholt/wilhelm-docs/blob/master/bmbt/49.md
DIAL_DIRECTION_BIT = 0b1000_0000
DIAL_STEPS_MASK = 0b0001_1111

# --- Зажигание, IKE 0x80 -----------------------------------------------------

IGNITION = {0x00: "выключено", 0x01: "Kl.R", 0x03: "Kl.15", 0x07: "стартер"}


def _bcd(value: int) -> int:
    """Двоично-десятичное число: 0x09 это девять, а не девять шестнадцатеричных."""
    return (value >> 4) * 10 + (value & 0x0F)


def _cdc(frame: Frame) -> str | None:
    if frame.dst == 0x18:
        head = CDC_REQUEST.get(frame.data[0])
        if head is None:
            return None
        if frame.data[0] == 0x38 and len(frame.data) >= 2:
            cmd = CDC_COMMAND.get(frame.data[1], f"код {frame.data[1]:02X}")
            return f"радио → чейнджеру: {cmd}"
        return f"радио → чейнджеру: {head}"
    if frame.src != 0x18:
        return None
    if frame.data[0] == 0x02:
        return "чейнджер: я здесь"
    if frame.data[0] == 0x39 and len(frame.data) >= CDC_STATUS_MIN_LEN:
        disc = _bcd(frame.data[CDC_STATUS_DISC])
        track = _bcd(frame.data[CDC_STATUS_TRACK])
        return f"чейнджер: диск {disc}, трек {track}"
    return None


def _monitor(frame: Frame) -> str | None:
    if frame.data[0] != 0x4F or len(frame.data) < 2:
        return None
    if frame.dst != 0xF0:
        return None
    b1 = frame.data[1]
    power = "включён" if b1 & 0b0001_0000 else "выключен"
    source = BMBT_SOURCE.get(b1 & 0b0000_0011, f"код {b1 & 0b11}")
    text = f"монитор: {power}, источник {source}"
    if len(frame.data) >= 3:
        b2 = frame.data[2]
        out = BMBT_OUTPUT.get(b2 & 0b0000_0011, f"код {b2 & 0b11}")
        aspect = BMBT_ASPECT.get((b2 >> 4) & 0b1111, "?")
        text += f", {aspect}, {out}"
    return text


def _mfl(frame: Frame) -> str | None:
    if frame.src != 0x50 or len(frame.data) < 2:
        return None
    if frame.data[0] == 0x3B:
        value = frame.data[1]
        button = MFL_BUTTON.get(value & MFL_BUTTON_MASK)
        if button is None:
            return f"руль: код {value:02X}"
        state = MFL_STATE.get(value & MFL_STATE_MASK, "состояние ?")
        return f"руль: {button}, {state}"
    if frame.data[0] == 0x32:
        value = frame.data[1]
        direction = "громче" if value & 0b0000_0001 else "тише"
        steps = (value >> 4) & 0b0000_1111
        return f"руль: {direction} на {steps}"
    return None


def _dial(frame: Frame) -> str | None:
    """Крутилка монитора. Штатно BMBT 0xF0 шлёт это навигации GT 0x3B."""
    if frame.src != 0xF0 or frame.data[0] not in (0x48, 0x49) or len(frame.data) < 2:
        return None
    value = frame.data[1]
    if frame.data[0] == 0x49:
        direction = "вправо" if value & DIAL_DIRECTION_BIT else "влево"
        return f"крутилка монитора: {direction} на {value & DIAL_STEPS_MASK}"
    return f"кнопка монитора: код {value:02X}"


def _ignition(frame: Frame) -> str | None:
    if frame.src != 0x80 or frame.data[0] != 0x11 or len(frame.data) < 2:
        return None
    return f"зажигание: {IGNITION.get(frame.data[1], f'код {frame.data[1]:02X}')}"


_DECODERS = (_cdc, _monitor, _mfl, _dial, _ignition)


def describe(frame: Frame) -> str | None:
    """Человеческое описание кадра, либо None если сообщение незнакомое."""
    for decoder in _DECODERS:
        try:
            text = decoder(frame)
        except IndexError:
            continue
        if text:
            return text
    return None

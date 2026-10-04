"""Кадры I-Bus: разбор, сборка, контрольная сумма.

Формат кадра: SRC LEN DST DATA... XOR
  SRC  — адрес источника
  LEN  — число байтов после LEN: DST + DATA + XOR
  XOR  — исключающее ИЛИ всех предыдущих байтов кадра

Пример: 68 03 18 01 72 — радио (0x68) опрашивает чейнджер (0x18).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Адреса блоков на шине. Списки собраны сообществом, для своей машины
# всё равно сверяйте снифером.
DEVICES = {
    0x00: "GM",
    0x18: "CDC",
    0x3B: "GT",
    0x3F: "DIA",
    0x43: "MENU",
    0x44: "EWS",
    0x50: "MFL",
    0x51: "MID",
    0x5B: "IHKA",
    0x60: "PDC",
    0x68: "RAD",
    0x6A: "DSP",
    0x7F: "NAV",
    0x80: "IKE",
    0xBB: "TV",
    0xBF: "LCM",
    0xC0: "MID_TEXT",
    0xC8: "TEL",
    0xD0: "LCM_D0",
    0xE7: "OBC_TEXT",
    0xED: "VM",
    0xF0: "BMBT",
    0xFF: "BROADCAST",
}

MIN_FRAME_LEN = 5  # SRC LEN DST DATA(>=1) XOR
MAX_FRAME_LEN = 64


def name(addr: int) -> str:
    """Короткое имя блока по адресу, либо шестнадцатеричный код."""
    return DEVICES.get(addr, f"{addr:02X}")


def checksum(data: bytes) -> int:
    """XOR всех байтов."""
    acc = 0
    for b in data:
        acc ^= b
    return acc


class FrameError(ValueError):
    """Кадр не прошёл проверку."""


@dataclass(frozen=True)
class Frame:
    src: int
    dst: int
    data: bytes

    def __post_init__(self) -> None:
        for label, value in (("src", self.src), ("dst", self.dst)):
            if not 0 <= value <= 0xFF:
                raise FrameError(f"{label} вне диапазона байта: {value}")
        if not self.data:
            raise FrameError("кадр без данных не бывает")
        if len(self.data) + 4 > MAX_FRAME_LEN:
            raise FrameError(f"кадр длиннее {MAX_FRAME_LEN} байт")

    @property
    def length_byte(self) -> int:
        """Значение байта LEN: DST + DATA + XOR."""
        return len(self.data) + 2

    def to_bytes(self) -> bytes:
        """Собрать кадр целиком, контрольная сумма считается здесь."""
        body = bytes([self.src, self.length_byte, self.dst]) + self.data
        return body + bytes([checksum(body)])

    @classmethod
    def parse(cls, raw: bytes) -> "Frame":
        """Разобрать ровно один кадр. Бросает FrameError при любой беде."""
        if len(raw) < MIN_FRAME_LEN:
            raise FrameError(f"слишком короткий кадр: {len(raw)} байт")
        expected = raw[1] + 2
        if len(raw) != expected:
            raise FrameError(f"длина не сходится: LEN={raw[1]}, байтов {len(raw)}, ждали {expected}")
        if checksum(raw[:-1]) != raw[-1]:
            raise FrameError(
                f"контрольная сумма не сходится: в кадре {raw[-1]:02X}, посчитали {checksum(raw[:-1]):02X}"
            )
        return cls(src=raw[0], dst=raw[2], data=bytes(raw[3:-1]))

    def hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.to_bytes())

    def __str__(self) -> str:
        payload = " ".join(f"{b:02X}" for b in self.data)
        return f"{name(self.src):>9} → {name(self.dst):<9} {payload}"


@dataclass
class Parser:
    """Потоковый разборщик: кормите байтами, забирайте кадры.

    Границу кадра определяем по байту длины, а рассинхронизацию лечим
    сдвигом на один байт. Дополнительно кадр считается оборванным, если
    между байтами прошла пауза: вызовите `flush()` по таймауту приёма.
    """

    buffer: bytearray = field(default_factory=bytearray)
    resyncs: int = 0        # сколько раз пришлось искать начало кадра заново
    lost_bytes: int = 0     # сколько байтов выброшено как мусор

    def feed(self, chunk: bytes) -> list[Frame]:
        """Добавить принятые байты и вернуть все кадры, которые сложились."""
        self.buffer.extend(chunk)
        frames: list[Frame] = []
        while True:
            frame = self._take_one()
            if frame is None:
                return frames
            frames.append(frame)

    def _take_one(self) -> Frame | None:
        while True:
            if len(self.buffer) < MIN_FRAME_LEN:
                return None
            total = self.buffer[1] + 2
            if not MIN_FRAME_LEN <= total <= MAX_FRAME_LEN:
                self._drop(1)
                continue
            if len(self.buffer) < total:
                # Кадр ещё летит. Искать другое начало прямо сейчас нельзя:
                # внутри данных может случайно оказаться последовательность
                # с сошедшейся суммой, и тогда разбор одного и того же потока
                # зависел бы от того, как он нарезан на порции чтения.
                return None
            candidate = bytes(self.buffer[:total])
            try:
                frame = Frame.parse(candidate)
            except FrameError:
                self._drop(1)
                continue
            del self.buffer[:total]
            return frame

    def recover(self) -> list[Frame]:
        """Восстановиться после обрыва: вызывать, когда в линии наступила пауза.

        Пауза означает, что недособранный кадр уже не придёт: либо был
        мусор, либо кадр оборвала коллизия. Ищем в буфере начало целого
        кадра, всё до него выбрасываем. Если ничего годного нет, буфер
        очищается целиком.
        """
        if not self.buffer:
            return []
        offset = self._find_frame_start()
        if offset is None:
            self.lost_bytes += len(self.buffer)
            self.buffer.clear()
            return []
        self._drop(offset)
        return self.feed(b"")

    def _find_frame_start(self) -> int | None:
        """Смещение, начиная с которого в буфере лежит целый годный кадр."""
        for offset in range(len(self.buffer) - MIN_FRAME_LEN + 1):
            total = self.buffer[offset + 1] + 2
            if not MIN_FRAME_LEN <= total <= MAX_FRAME_LEN:
                continue
            if offset + total > len(self.buffer):
                continue
            try:
                Frame.parse(bytes(self.buffer[offset : offset + total]))
            except FrameError:
                continue
            return offset
        return None

    def _drop(self, count: int) -> None:
        """Выбросить испорченные байты."""
        if count <= 0:
            return
        self.resyncs += 1
        self.lost_bytes += count
        del self.buffer[:count]

    def flush(self) -> None:
        """Выбросить недособранный хвост без попытки восстановления."""
        self.lost_bytes += len(self.buffer)
        self.buffer.clear()

    @property
    def errors(self) -> int:
        """Совместимость со старым именем: число рассинхронизаций."""
        return self.resyncs

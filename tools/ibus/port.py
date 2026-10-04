"""Работа с физической шиной через последовательный порт.

Шина однопроводная и без ведущего, поэтому передача устроена так:
  1. дождаться тишины на линии,
  2. отправить байт и тут же прочитать его эхо,
  3. если эхо не совпало, значит говорил кто-то ещё — отступить и повторить.

Без эха отправлять нельзя: коллизии на I-Bus никто не разруливает аппаратно.

Тайминги подобраны для 9600 бод, где один байт занимает около 1,04 мс.
Реальные задержки USB-адаптера сюда не заложены: у FTDI по умолчанию
таймер задержки 16 мс, и его надо либо уменьшать в драйвере, либо
увеличивать ECHO_TIMEOUT. Это проверяется на живом адаптере.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import serial  # pyserial

from .frame import Frame, Parser

BAUDRATE = 9600
IDLE_SECONDS = 0.010       # тишина на линии перед передачей
GAP_SECONDS = 0.020        # пауза, после которой кадр считается оборванным
ECHO_TIMEOUT = 0.050       # сколько ждать эхо одного байта
READ_TIMEOUT = 0.005       # таймаут одного чтения порта
SEND_ATTEMPTS = 5


class CollisionError(RuntimeError):
    """Не удалось передать кадр: линию всё время занимал кто-то другой."""


@dataclass
class Bus:
    """Одно подключение к шине.

    Открывается из кода так:

        with Bus.open("/dev/tty.usbserial-XXXX") as bus:
            for frame in bus.read():
                print(frame)
    """

    serial: serial.Serial
    parser: Parser
    last_activity: float = 0.0
    pending: list[Frame] = field(default_factory=list)

    @classmethod
    def open(cls, device: str, baudrate: int = BAUDRATE) -> "Bus":
        port = serial.Serial(
            port=device,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_EVEN,
            stopbits=serial.STOPBITS_ONE,
            timeout=READ_TIMEOUT,
        )
        port.reset_input_buffer()
        return cls(serial=port, parser=Parser())

    def __enter__(self) -> "Bus":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.serial.close()

    # --- приём ---------------------------------------------------------------

    def poll(self) -> list[Frame]:
        """Прочитать накопившееся и вернуть готовые кадры.

        Сюда же попадают кадры, принятые во время ожидания тишины перед
        передачей: терять их нельзя, иначе прошивка пропустит запрос,
        на который как раз собиралась ответить.
        """
        frames = self._take_pending()
        chunk = self.serial.read(256)
        now = time.monotonic()
        if chunk:
            self.last_activity = now
            frames.extend(self.parser.feed(chunk))
            return frames
        if self.parser.buffer and now - self.last_activity > GAP_SECONDS:
            # Пауза длиннее межбайтового интервала: хвост оборван.
            # Пробуем вытащить из мусора то, что ещё можно разобрать.
            frames.extend(self.parser.recover())
        return frames

    def read(self):
        """Бесконечный поток кадров. Удобно для снифера."""
        while True:
            for frame in self.poll():
                yield frame

    def _take_pending(self) -> list[Frame]:
        if not self.pending:
            return []
        frames, self.pending = self.pending, []
        return frames

    # --- передача ------------------------------------------------------------

    def _wait_idle(self, timeout: float = 1.0) -> bool:
        """Дождаться, пока линия замолчит. False, если так и не дождались.

        Всё, что придёт за это время, разбирается и откладывается в
        `pending`, а не выбрасывается.
        """
        deadline = time.monotonic() + timeout
        quiet_since = time.monotonic()
        while time.monotonic() < deadline:
            waiting = self.serial.in_waiting
            if waiting:
                chunk = self.serial.read(waiting)
                self.pending.extend(self.parser.feed(chunk))
                quiet_since = time.monotonic()
                self.last_activity = quiet_since
                continue
            if time.monotonic() - quiet_since >= IDLE_SECONDS:
                return True
            time.sleep(0.001)
        return False

    def send(self, frame: Frame, attempts: int = SEND_ATTEMPTS) -> None:
        """Отправить кадр, сверяя эхо каждого байта.

        Бросает CollisionError, если за отведённое число попыток
        линию занять не удалось.
        """
        raw = frame.to_bytes()
        for _ in range(attempts):
            if not self._wait_idle():
                continue
            if self._write_with_echo(raw):
                return
            time.sleep(0.002 + random.random() * 0.008)
        raise CollisionError(f"не удалось передать {frame.hex()}")

    def _read_echo(self) -> bytes:
        """Прочитать один байт эха, ожидая до ECHO_TIMEOUT."""
        deadline = time.monotonic() + ECHO_TIMEOUT
        while time.monotonic() < deadline:
            byte = self.serial.read(1)
            if byte:
                return byte
        return b""

    def _write_with_echo(self, raw: bytes) -> bool:
        for byte in raw:
            self.serial.write(bytes([byte]))
            if self._read_echo() != bytes([byte]):
                # Либо коллизия, либо эхо потерялось. И то и другое —
                # повод прекратить передачу и начать заново. Входной
                # буфер не сбрасываем: там могут лежать чужие кадры,
                # а мусор отсеется по контрольной сумме.
                self.parser.flush()
                return False
        self.last_activity = time.monotonic()
        return True

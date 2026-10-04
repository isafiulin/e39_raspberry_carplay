#!/usr/bin/env python3
"""Имитатор радио BM54 для стенда.

Играет роль машины, пока машины нет: опрашивает чейнджер так же, как это
делает настоящее радио, и печатает, что ему ответили. По нажатию клавиш
шлёт кнопки монитора и руля, чтобы проверять реакцию прошивки.

    python3 radio_sim.py /dev/tty.usbserial-XXXX

Клавиши во время работы:
    p  опрос чейнджера вручную
    1  команда «играть»
    0  команда «стоп»
    l  крутилка влево
    r  крутилка вправо
    t  кнопка TV на мониторе
    i  зажигание Kl.15 от IKE
    o  зажигание выключено
    q  выход
"""

from __future__ import annotations

import argparse
import contextlib
import queue
import sys
import termios
import threading
import time
import tty

from ibus import Frame, describe
from ibus.port import Bus, CollisionError

RAD, CDC, BMBT, MFL, IKE, VM, GT = 0x68, 0x18, 0xF0, 0x50, 0x80, 0xED, 0x3B

POLL_INTERVAL = 1.0  # как часто настоящее радио дёргает чейнджер

KEYS: dict[str, tuple[str, Frame]] = {
    "p": ("опрос чейнджера", Frame(RAD, CDC, bytes([0x01]))),
    "1": ("чейнджеру: играть", Frame(RAD, CDC, bytes([0x38, 0x03, 0x00]))),
    "0": ("чейнджеру: стоп", Frame(RAD, CDC, bytes([0x38, 0x01, 0x00]))),
    # крутилку BMBT штатно адресует навигации GT, а не радио:
    # https://github.com/piersholt/wilhelm-docs/blob/master/bmbt/49.md
    "l": ("крутилка влево", Frame(BMBT, GT, bytes([0x49, 0x01]))),
    "r": ("крутилка вправо", Frame(BMBT, GT, bytes([0x49, 0x81]))),
    "t": ("кнопка TV", Frame(BMBT, VM, bytes([0x48, 0x30]))),
    "i": ("зажигание Kl.15", Frame(IKE, 0xFF, bytes([0x11, 0x03]))),
    "o": ("зажигание выключено", Frame(IKE, 0xFF, bytes([0x11, 0x00]))),
}


@contextlib.contextmanager
def raw_terminal():
    """Посимвольный ввод без Enter, с гарантированным восстановлением.

    Восстановление держим здесь, в основном потоке: в потоке-читателе
    оно не выполнится ни при Ctrl+C, ни при ошибке порта, и терминал
    останется сломанным.
    """
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def read_keys(out: queue.Queue[str]) -> None:
    """Читает по одной клавише и складывает в очередь."""
    while True:
        ch = sys.stdin.read(1)
        if not ch:
            return
        out.put(ch)
        if ch == "q":
            return


def show(prefix: str, frame: Frame) -> None:
    text = describe(frame)
    print(f"{prefix} {frame.hex():<26} {frame}" + (f"  {text}" if text else ""), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Имитатор радио BM54 на шине I-Bus")
    parser.add_argument("device", help="последовательный порт")
    parser.add_argument("--no-poll", action="store_true", help="не опрашивать чейнджер автоматически")
    args = parser.parse_args(argv)

    keys: queue.Queue[str] = queue.Queue()
    print(__doc__.split("Клавиши")[1].join(["Клавиши", ""]), file=sys.stderr)

    next_poll = time.monotonic()
    with raw_terminal(), Bus.open(args.device) as bus:
        threading.Thread(target=read_keys, args=(keys,), daemon=True).start()
        while True:
            for frame in bus.poll():
                show("  ←", frame)

            try:
                key = keys.get_nowait()
            except queue.Empty:
                key = None

            if key == "q":
                break
            if key in KEYS:
                label, frame = KEYS[key]
                try:
                    bus.send(frame)
                    show(f"  → {label}:", frame)
                except CollisionError as exc:
                    print(f"  ! {exc}", flush=True)

            now = time.monotonic()
            if not args.no_poll and now >= next_poll:
                next_poll = now + POLL_INTERVAL
                poll = Frame(RAD, CDC, bytes([0x01]))
                try:
                    bus.send(poll)
                    show("  → опрос:", poll)
                except CollisionError as exc:
                    print(f"  ! {exc}", flush=True)

            time.sleep(0.002)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

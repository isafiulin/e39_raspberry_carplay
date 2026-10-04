#!/usr/bin/env python3
"""Отправить произвольный кадр в шину.

Контрольная сумма считается сама, в командной строке её писать не надо:

    python3 send.py /dev/tty.usbserial-XXXX 68 18 01
    python3 send.py /dev/tty.usbserial-XXXX ED F0 4F 11 11

Первый аргумент после порта — источник, второй — получатель,
остальное — данные. Всё в шестнадцатеричном виде.
"""

from __future__ import annotations

import argparse

from ibus import Frame, describe
from ibus.port import Bus, CollisionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Отправка кадра в I-Bus")
    parser.add_argument("device", help="последовательный порт")
    parser.add_argument("bytes", nargs="+", help="SRC DST DATA... в hex, без контрольной суммы")
    parser.add_argument("--repeat", type=int, default=1, help="сколько раз отправить")
    parser.add_argument("--interval", type=float, default=0.5, help="пауза между повторами, секунды")
    args = parser.parse_args(argv)

    try:
        values = [int(token, 16) for token in args.bytes]
    except ValueError as exc:
        parser.error(f"байты должны быть шестнадцатеричными: {exc}")
    if len(values) < 3:
        parser.error("нужно минимум три байта: источник, получатель и один байт данных")

    frame = Frame(src=values[0], dst=values[1], data=bytes(values[2:]))
    text = describe(frame)
    print(f"Отправляю: {frame.hex()}   {frame}" + (f"  {text}" if text else ""))

    import time

    if args.repeat < 1:
        parser.error("--repeat должен быть не меньше единицы")
    if args.interval < 0:
        parser.error("--interval не может быть отрицательным")

    sent = 0
    with Bus.open(args.device) as bus:
        for i in range(args.repeat):
            try:
                bus.send(frame)
                sent += 1
                print(f"  {i + 1}/{args.repeat} ушло")
            except CollisionError as exc:
                print(f"  {i + 1}/{args.repeat} не ушло: {exc}")
            if i + 1 < args.repeat:
                time.sleep(args.interval)
    # ненулевой код, если не ушло ничего: скриптам это важно
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())

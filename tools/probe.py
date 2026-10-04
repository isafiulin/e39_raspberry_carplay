#!/usr/bin/env python3
"""Отправить кадр и сразу послушать ответ тем же портом.

Обычная связка send.py плюс sniff.py для диагностики не годится: модуль
отвечает за единицы миллисекунд, а второй процесс успевает открыть порт
только через сотни. Здесь порт открывается один раз.

    python3 probe.py /dev/ttyUSB0 3F ED 00 --wait 2

Первый байт после порта — источник, второй — получатель, остальное данные.
Контрольная сумма считается сама. Ничего, кроме одного кадра, не передаётся.
"""

from __future__ import annotations

import argparse
import time

from ibus import Frame, describe
from ibus.port import Bus, CollisionError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Отправить кадр и послушать ответ")
    parser.add_argument("device", help="последовательный порт")
    parser.add_argument("bytes", nargs="+", help="SRC DST DATA... в hex, без суммы")
    parser.add_argument("--wait", type=float, default=2.0, help="сколько слушать после отправки, секунды")
    args = parser.parse_args(argv)

    try:
        values = [int(token, 16) for token in args.bytes]
    except ValueError as exc:
        parser.error(f"байты должны быть шестнадцатеричными: {exc}")
    if len(values) < 3:
        parser.error("нужно минимум три байта: источник, получатель и один байт данных")

    frame = Frame(src=values[0], dst=values[1], data=bytes(values[2:]))
    print(f"Отправляю: {frame.hex()}   {frame}")

    with Bus.open(args.device) as bus:
        try:
            bus.send(frame)
        except CollisionError as exc:
            print(f"Не ушло: {exc}")
            return 1
        print("Ушло. Слушаю ответ.")
        started = time.monotonic()
        seen = 0
        while time.monotonic() - started < args.wait:
            for answer in bus.poll():
                seen += 1
                mark = "  <<<" if answer.src == frame.dst else "     "
                text = describe(answer)
                print(f"{mark} {time.monotonic() - started:6.3f}  {answer.hex()}   {answer}" + (f"  {text}" if text else ""))
            time.sleep(0.002)
        if not seen:
            print("Тишина: ни одного кадра за это время.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

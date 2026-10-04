#!/usr/bin/env python3
"""Опросить устройства на шине запросом идентификации.

Каждому известному адресу отправляется один и тот же читающий запрос 0x00
от адреса диагностики 0x3F. Это то же, что делает Scan в NavCoder.
Ничего не записывается: опкод один на всех, меняется только получатель.

Коды ответа DS2: A0 принято, A1 занят, A2 занят, FF ошибка или не поддержано.

    python3 scan.py /dev/ttyUSB0
"""

from __future__ import annotations

import argparse
import time

from ibus import Frame, DEVICES
from ibus.port import Bus, CollisionError

BROADCAST = {0x00, 0xBF, 0xFF}
DIA = 0x3F
STATUS = {0xA0: "принято", 0xA1: "занят", 0xA2: "занят", 0xFF: "ошибка или не поддержано"}


def printable(data: bytes) -> str:
    return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Опрос устройств на I-Bus")
    parser.add_argument("device", help="последовательный порт")
    parser.add_argument("--wait", type=float, default=0.4, help="сколько ждать ответа, секунды")
    args = parser.parse_args(argv)

    targets = sorted(addr for addr in DEVICES if addr not in BROADCAST and addr != DIA)
    print(f"Опрашиваю {len(targets)} адресов запросом 00 от {DIA:02X}.\n")

    found = 0
    with Bus.open(args.device) as bus:
        for addr in targets:
            name = DEVICES.get(addr, "?")
            try:
                bus.send(Frame(src=DIA, dst=addr, data=bytes([0x00])))
            except CollisionError:
                print(f"{addr:02X} {name:10} линия занята, пропускаю")
                continue
            started = time.monotonic()
            answered = False
            while time.monotonic() - started < args.wait:
                for frame in bus.poll():
                    if frame.src == addr and frame.dst == DIA:
                        answered = True
                        found += 1
                        status = STATUS.get(frame.data[0], f"код {frame.data[0]:02X}")
                        payload = frame.data[1:]
                        print(f"{addr:02X} {name:10} {status}")
                        if payload:
                            print(f"   {payload.hex(' ').upper()}")
                            print(f"   текст: {printable(payload)}")
                time.sleep(0.002)
            if not answered:
                print(f"{addr:02X} {name:10} молчит")
    print(f"\nОтветили: {found}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Снифер I-Bus: пишет всё, что происходит на шине, в консоль и в файл.

    python3 sniff.py /dev/tty.usbserial-A50285BI
    python3 sniff.py /dev/tty.usbserial-A50285BI --log записи/меню-tv.log

Формат строки: время от старта, сырые байты, кто кому, расшифровка.
Лог потом скармливается replay и служит источником истины для прошивки.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from ibus import Frame, describe
from ibus.port import Bus


def format_line(elapsed: float, frame: Frame) -> str:
    text = describe(frame)
    suffix = f"  {text}" if text else ""
    return f"{elapsed:9.3f}  {frame.hex():<26}  {frame}{suffix}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Снифер шины I-Bus")
    parser.add_argument("device", help="последовательный порт, например /dev/tty.usbserial-XXXX")
    parser.add_argument("--log", type=Path, help="файл для записи, дописывается")
    parser.add_argument("--src", type=lambda s: int(s, 16), help="показывать только от этого адреса, hex")
    parser.add_argument("--dst", type=lambda s: int(s, 16), help="показывать только этому адресу, hex")
    args = parser.parse_args(argv)

    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
    log = args.log.open("a", encoding="utf-8") if args.log else None
    started = time.monotonic()
    count = 0

    try:
        with Bus.open(args.device) as bus:
            print(f"Слушаю {args.device}. Ctrl+C чтобы остановить.", file=sys.stderr)
            for frame in bus.read():
                if args.src is not None and frame.src != args.src:
                    continue
                if args.dst is not None and frame.dst != args.dst:
                    continue
                count += 1
                line = format_line(time.monotonic() - started, frame)
                print(line, flush=True)
                if log:
                    log.write(line + "\n")
                    log.flush()
    except KeyboardInterrupt:
        print(f"\nПоймано кадров: {count}, сбоев разбора: {bus.parser.errors}", file=sys.stderr)
    finally:
        if log:
            log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

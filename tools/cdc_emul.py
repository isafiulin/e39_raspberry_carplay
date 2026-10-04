#!/usr/bin/env python3
"""Эмулятор чейнджера отдельно от обработчика: первая проверка варианта 2.

ПОКА НЕ ИСПОЛЬЗУЕТСЯ в машине. Нужен для одного вопроса: появится ли CD
в списке источников радио, если на шине отвечает наш чейнджер. Звук этим
не проверяется — для него нужен кабель во вход чейнджера.

Передача выключена по умолчанию, как у agent.py: без флага скрипт только
печатает, что ответил бы.

    # на стенде, в паре с radio_sim.py на втором кабеле
    python3 cdc_emul.py /dev/tty.usbserial-XXXX --razreshit-peredachu

    # в машине: сначала послушать, что спрашивает радио
    python3 cdc_emul.py /dev/ttyUSB0

Штатный чейнджер, если он стоит, перед этим отключить: два устройства
на одном адресе 0x18 радио запутают.
"""

from __future__ import annotations

import argparse
import time

from ibus import Frame, describe
from ibus.cdc import Changer
from ibus.events import Ignition, event
from ibus.port import Bus, CollisionError


def show(prefix: str, frame: Frame) -> None:
    text = describe(frame)
    print(f"{prefix} {frame.hex():<32} {frame}" + (f"  {text}" if text else ""), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Эмулятор CD-чейнджера на шине I-Bus")
    parser.add_argument("device", help="последовательный порт")
    parser.add_argument("--razreshit-peredachu", action="store_true", dest="transmit", help="действительно отвечать в шину")
    args = parser.parse_args(argv)

    changer = Changer()

    def send(bus: Bus, frames: list[Frame]) -> None:
        for frame in frames:
            if not args.transmit:
                show("  не отправлено:", frame)
                continue
            try:
                bus.send(frame)
                show("  →", frame)
            except CollisionError as exc:
                print(f"  ! НЕ УШЛО {frame.hex()}: {exc}", flush=True)

    with Bus.open(args.device) as bus:
        was_playing = changer.playing
        while True:
            now = time.monotonic()
            send(bus, changer.tick(now))
            for frame in bus.poll():
                if frame.src == 0x18:
                    # Своё эхо или штатный чейнджер — второе плохо, видно в выводе.
                    continue
                ev = event(frame)
                if isinstance(ev, Ignition) and ev.state == "выключено":
                    changer.reset()
                answer = changer.on_frame(frame, now)
                if answer.frames or frame.dst == 0x18:
                    show("  ←", frame)
                send(bus, answer.frames)
                if answer.track is not None:
                    print(f"  трек: {'следующий' if answer.track else 'предыдущий'}", flush=True)
            if changer.playing != was_playing:
                was_playing = changer.playing
                print(f"  радио {'играет нас' if was_playing else 'ушло с CD'}", flush=True)
            time.sleep(0.002)


if __name__ == "__main__":
    raise SystemExit(main())

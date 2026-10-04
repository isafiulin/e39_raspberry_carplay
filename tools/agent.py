#!/usr/bin/env python3
"""Обработчик кнопок монитора для CarPlay.

Слушает шину, показывает и прячет нашу картинку, передаёт крутилку и выбор
в CarPlay. Передача в шину выключена по умолчанию.

    # с настоящим процессом CarPlay
    python3 agent.py /dev/ttyUSB0 --sokset --razreshit-peredachu

    # прогнать записанный лог, без машины и без кабеля
    python3 agent.py --iz-loga ../logs/20260930-knopki-i-rezhim-tv.log --telefon

    # посмотреть, что сервис собирается делать на живой шине, ничего не отправляя
    python3 agent.py /dev/ttyUSB0 --telefon

    # то же, но по-настоящему
    python3 agent.py /dev/ttyUSB0 --telefon --razreshit-peredachu
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from agent.carplay import LogBackend
from agent.logs import LOG_DIR, setup
from agent.dongle import DEFAULT_PATH, DongleBackend
from agent.replay import frames_from_log
from agent.runner import Runner
from ibus.port import Bus

# Как часто проверять, не появился ли кабель. Чаще незачем: это не гонка.
RETRY_SECONDS = 3.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Обработчик кнопок монитора для CarPlay")
    parser.add_argument("device", nargs="?", help="последовательный порт")
    parser.add_argument("--iz-loga", dest="log", type=Path, help="проиграть записанный лог вместо живой шины")
    parser.add_argument("--telefon", action="store_true", help="считать, что телефон подключён (для стенда без донгла)")
    parser.add_argument("--sokset", nargs="?", const=DEFAULT_PATH, help=f"работать с настоящим процессом CarPlay через сокет (по умолчанию {DEFAULT_PATH})")
    parser.add_argument("--razreshit-peredachu", action="store_true", dest="transmit", help="действительно отправлять кадры в шину")
    parser.add_argument("--vse-kadry", action="store_true", dest="verbose", help="писать в журнал и те кадры, которые нам неинтересны")
    args = parser.parse_args(argv)

    log = setup("agent", verbose=args.verbose)
    log.info("журнал пишется в %s", LOG_DIR / "agent.log")
    backend = DongleBackend(args.sokset) if args.sokset else LogBackend(phone=args.telefon)

    if args.log:
        if not args.log.exists():
            log.error("нет такого файла: %s", args.log)
            return 1
        runner = Runner(None, backend, transmit=False, verbose=args.verbose)
        runner.replay(frames_from_log(args.log))
        return 0

    if not args.device:
        parser.error("нужен порт или --iz-loga")

    # Служба живёт постоянно и ждёт кабель, а не падает без него. Падать здесь
    # нельзя: systemd поднимал бы процесс каждые несколько секунд впустую, и
    # журнал заполнился бы одинаковыми строками. Кабель могут воткнуть позже,
    # выдернуть в дороге или задеть в багажнике — во всех случаях надо просто
    # дождаться его снова.
    device = Path(args.device)
    waiting_logged = False
    try:
        while True:
            if not device.exists():
                if not waiting_logged:
                    log.info("жду кабель шины на %s", device)
                    waiting_logged = True
                time.sleep(RETRY_SECONDS)
                continue
            waiting_logged = False
            try:
                with Bus.open(str(device)) as bus:
                    Runner(bus, backend, transmit=args.transmit, verbose=args.verbose).run()
            except OSError as exc:
                # Кабель выдернули или адаптер отвалился. Это не повод
                # прекращать работу: ждём и пробуем снова.
                log.warning("порт %s отвалился: %s", device, exc)
                time.sleep(RETRY_SECONDS)
    except KeyboardInterrupt:
        log.info("остановлено с клавиатуры")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

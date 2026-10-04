"""Сервис: слушает шину, кормит автомат, выполняет его решения.

Передача в шину по умолчанию выключена. Чтобы сервис действительно говорил,
нужен явный флаг: на живой машине случайный запуск не должен ничего менять.
"""

from __future__ import annotations

import time

from ibus import Frame, describe
from ibus.events import event
from ibus.port import Bus, CollisionError

from .carplay import Backend
from .logs import setup
from .state import Agent, Back, Command, HidePicture, Navigate, LeaveTelevision, PressMode, Select, ShowPicture, Track

DIA_AS_MONITOR = 0x3B   # прикидываемся монитором: кадры картинки шлёт он
TV_MODULE = 0xBB

SHOW = Frame(src=DIA_AS_MONITOR, dst=TV_MODULE, data=bytes([0x4F, 0x01, 0x00]))
HIDE = Frame(src=DIA_AS_MONITOR, dst=TV_MODULE, data=bytes([0x4F, 0x02, 0x00]))

# Нажатие MODE за владельца: те же кадры, что шлёт монитор. Сняты с машины.
BMBT = 0xF0
RADIO = 0x68
MODE_DOWN = Frame(src=BMBT, dst=RADIO, data=bytes([0x48, 0x23]))
MODE_UP = Frame(src=BMBT, dst=RADIO, data=bytes([0x48, 0xA3]))

# Вернуть звук радио. Кадр монитора, снятый с машины при выходе из Television.
RETURN_AUDIO = Frame(src=DIA_AS_MONITOR, dst=RADIO, data=bytes([0x4E, 0x00, 0x00]))


class Runner:
    def __init__(self, bus: Bus | None, backend: Backend, *, transmit: bool = False, verbose: bool = False) -> None:
        self.bus = bus
        self.backend = backend
        self.transmit = transmit
        self.verbose = verbose
        self.agent = Agent()
        self.log = setup("agent", verbose=verbose)

    def replay(self, frames) -> None:
        """Прогнать готовые кадры вместо живой шины. Передача всегда выключена."""
        self.transmit = False
        self.log.info("проигрываю записанный лог, передача выключена")
        self._apply(self.agent.phone_connected(self.backend.connected()))
        for frame in frames:
            self._on_frame(frame)

    def run(self) -> None:
        mode = "передача разрешена" if self.transmit else "только слушаю, передача выключена"
        self.log.info("сервис запущен, %s", mode)
        last_phone_check = 0.0
        while True:
            now = time.monotonic()
            if now - last_phone_check > 0.5:
                last_phone_check = now
                was = self.agent.phone
                commands = self.agent.phone_connected(self.backend.connected())
                if self.agent.phone != was:
                    self.log.info("телефон %s", "подключился" if self.agent.phone else "пропал")
                self._apply(commands)
            self._apply(self.agent.tick(now))
            for frame in self.bus.poll():
                self._on_frame(frame)
            time.sleep(0.002)

    # --- внутреннее ----------------------------------------------------------

    def _on_frame(self, frame: Frame) -> None:
        ev = event(frame)
        if ev is None:
            # Неинтересных кадров на шине большинство. В обычном режиме они
            # только мешают, но при разборе поломки нужны все.
            text = describe(frame)
            self.log.debug("%s  %s%s", frame.hex(), frame, f"  {text}" if text else "")
            return
        self.log.info("%s  %s", frame.hex(), ev)
        self._apply(self.agent.on_event(ev))

    def _apply(self, commands: list[Command]) -> None:
        for command in commands:
            if isinstance(command, ShowPicture):
                self._send(SHOW, "показать нашу картинку")
                # Заодно всегда отдаём звук радио. Если монитор когда-то
                # сказал ему «звук забирает ТВ», радио перестаёт отвечать
                # даже на кнопку MODE, и состояние залипает: звук идёт с
                # мёртвого входа модуля, а переключить источник нечем.
                # Команда безвредна, когда звук и так у радио.
                self._send(RETURN_AUDIO, "вернуть звук радио на всякий случай")
            elif isinstance(command, HidePicture):
                self._send(HIDE, "вернуть штатный экран")
            elif isinstance(command, Navigate):
                self.log.info("в CarPlay: %s на %d", "вправо" if command.right else "влево", command.steps)
                self.backend.navigate(command.right, command.steps)
            elif isinstance(command, Select):
                self.log.info("в CarPlay: выбор")
                self.backend.select()
            elif isinstance(command, Back):
                self.log.info("в CarPlay: назад")
                self.backend.back()
            elif isinstance(command, LeaveTelevision):
                # Порядок важен: сначала выйти из Television целиком, иначе
                # монитор продолжит считать себя хозяином звука.
                self._send(HIDE, "выйти из Television")
                time.sleep(0.2)
                self._send(RETURN_AUDIO, "вернуть звук радио")
                time.sleep(0.2)
                self._send(SHOW, "показать картинку своим кадром")
            elif isinstance(command, PressMode):
                self.log.info(
                    "ищу AUX: нажимаю MODE, попытка %d, сейчас источник %r",
                    self.agent.aux_attempts, self.agent.audio_source,
                )
                self._send(MODE_DOWN, "нажатие MODE")
                self._send(MODE_UP, "отпускание MODE")
            elif isinstance(command, Track):
                self.log.info("в CarPlay: %s трек", "следующий" if command.forward else "предыдущий")
                self.backend.track(command.forward)

    def _send(self, frame: Frame, why: str) -> None:
        if not self.transmit:
            self.log.info("не отправлено (передача выключена): %s  %s", frame.hex(), why)
            return
        try:
            self.bus.send(frame)
            self.log.info("отправлено: %s  %s", frame.hex(), why)
        except CollisionError as exc:
            # Шина занята или её вовсе нет. Важно видеть это в журнале:
            # снаружи такой отказ выглядит просто как «картинка не появилась».
            self.log.warning("НЕ УШЛО: %s  %s — %s", frame.hex(), why, exc)
        except OSError as exc:
            self.log.error("порт отказал при отправке %s: %s", frame.hex(), exc)
            raise

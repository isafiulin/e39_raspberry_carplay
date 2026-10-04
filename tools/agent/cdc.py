"""Звук через вход чейнджера: прослойка варианта 2 для обработчика.

ПОКА НЕ ИСПОЛЬЗУЕТСЯ. Сервис работает по варианту 1: звук на AUX, картинка
на AV. Здесь собрано то, что понадобится, если звук придётся перенести
во вход чейнджера, а картинку оставить на AV как есть.

Два варианта отличаются только звуком:

  вариант 1, AUX + AV   радио видит AUX сам, по резистору опознавания.
                        Наш ли звук — читаем по надписи радио. Источник
                        ищем нажатиями MODE (agent/state.py, PressMode).
  вариант 2, CDC + AV   радио видит чейнджер, только пока мы отвечаем ему
                        по шине (ibus/cdc.py). Наш ли звук — радио говорит
                        само командами «играть» и «стоп». Трек ± приходит
                        от радио командой чейнджеру.

Картинка, кнопки монитора, возврат звука кадром 4E 00 00 и всё остальное
в agent/state.py одинаковы для обоих вариантов.

Что поменять в обработчике, когда вариант 2 понадобится:

1. runner.py: на каждый кадр звать `CdcAudio.on_frame`, кадры из ответа
   отправлять сразу, вне очереди; `tick` звать в главном цикле. Эмулятор
   должен отвечать всегда, когда шина не спит, и даже без телефона —
   иначе радио выкинет CD из списка источников.
2. state.py: `our_audio` брать из `CdcAudio.our_audio`, а не из надписи
   радио. Кнопки руля «вперёд» и «назад» в варианте 2 не обрабатывать:
   радио само превратит их в команду чейнджеру, и трек переключится дважды.
3. Поиск источника нажатиями MODE: искать надпись CD вместо AUX. Как
   радио BM54 подписывает чейнджер на экране, ещё не видели.
4. Передачу эмулятора включать тем же флагом --razreshit-peredachu.

Что проверить в машине до этого — в docs/10-cheyndzher-bmw-4730en.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ibus import Frame
from ibus.cdc import Changer
from ibus.events import Ignition, event

from .state import Command, Track


@dataclass
class CdcAudio:
    changer: Changer = field(default_factory=Changer)

    @property
    def our_audio(self) -> bool:
        """Радио играет вход чейнджера, то есть нас."""
        return self.changer.playing

    def on_frame(self, frame: Frame, now: float) -> tuple[list[Frame], list[Command]]:
        """Кадр с шины. Возвращает, что отправить, и что передать CarPlay."""
        ev = event(frame)
        if isinstance(ev, Ignition) and ev.state == "выключено":
            self.changer.reset()
            return [], []
        answer = self.changer.on_frame(frame, now)
        commands: list[Command] = []
        if answer.track is not None:
            commands.append(Track(forward=answer.track))
        return answer.frames, commands

    def tick(self, now: float) -> list[Frame]:
        return self.changer.tick(now)

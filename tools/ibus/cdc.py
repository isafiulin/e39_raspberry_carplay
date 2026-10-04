"""Эмулятор CD-чейнджера: протокольная часть варианта 2.

ПОКА НЕ ИСПОЛЬЗУЕТСЯ. Рабочий вариант проекта — звук в штатный AUX радио
(вариант 1). Этот модуль лежит рядом на случай, если понадобится вариант 2:
звук идёт во вход чейнджера радио, а радио считает, что у него стоит CDC.
Картинка в обоих вариантах одна и та же — вход AV видеомодуля.

Здесь только логика, без порта и без сна, как и в agent/state.py: кадр
пришёл — вернули, что ответить. Время приходит снаружи.

Протокол сверен с двумя источниками, на нашей машине ещё не проверен:

* https://github.com/piersholt/wilhelm-docs/blob/master/cdc/38.md и 39.md
* BlueBus, firmware/application/handler/handler_ibus.c, HandlerIBusCDCStatus

Что известно про нашу машину: радио BM54 закодировано на чейнджер и само
его ищет — кадр 68 05 18 38 00 00 есть в логах 30.09.2026, хотя чейнджера нет.

Разговор устроен так:

  радио → CDC   01               опрос «ты здесь?»
  CDC   → радио 02 00            «здесь»
  CDC   → все   02 01            объявление о себе: после старта и если
                                 радио долго не спрашивало
  радио → CDC   38 cmd arg       команда: статус, стоп, играть, трек ±
  CDC   → радио 39 ...           статус в ответ на каждую команду

Главное правило из BlueBus: отвечать ровно то, что радио попросило, даже
если на деле мы ещё ничего не сделали. Иначе радио повторяет команду
снова и снова.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .frame import Frame

CDC = 0x18
RADIO = 0x68
BROADCAST = 0xFF

POLL = 0x01
PONG = 0x02
REQUEST = 0x38
STATUS = 0x39

# Команды радио, второй байт после 0x38.
CMD_STATUS = 0x00
CMD_STOP = 0x01
CMD_PAUSE = 0x02
CMD_PLAY = 0x03
CMD_SEEK = 0x04
CMD_TRACK_ALT = 0x05  # тот же трек ±, вариант некоторых радио
CMD_DISC = 0x06
CMD_SCAN = 0x07
CMD_RANDOM = 0x08
CMD_TRACK = 0x0A

# Байт состояния в ответе 0x39.
STAT_STOP = 0x00
STAT_PAUSE = 0x01
STAT_PLAYING = 0x02
STAT_FAST_REV = 0x04

# Байт функции в ответе 0x39.
FUNC_NOT_PLAYING = 0x02
FUNC_PLAYING = 0x09
FUNC_PAUSE = 0x0C
FUNC_SCAN = 0x19
FUNC_RANDOM = 0x29

# Монитор BMBT: один диск в магазине, диск 1. С семью дисками, как делает
# BlueBus без монитора, радио на BMBT рисует лишнее.
MAGAZINE_ONE_DISC = 0x01
DISC = 0x01
TRACK = 0x01

# Тайминги из BlueBus. Радио спрашивает статус примерно раз в 20 секунд;
# если опроса нет дольше 21 секунды, объявляемся заново.
ANNOUNCE_AFTER = 21.0


@dataclass(frozen=True)
class Answer:
    """Что эмулятор хочет сделать в ответ на кадр.

    `frames` — отправить в шину, и как можно скорее: BlueBus пишет, что
    радио может «потерять» чейнджер, если перед ответом увидит другой
    адресованный ему кадр. `track` — радио попросило следующий (True)
    или предыдущий (False) трек; передать в CarPlay.
    """

    frames: list[Frame] = field(default_factory=list)
    track: bool | None = None


@dataclass
class Changer:
    """Состояние эмулируемого чейнджера.

    `function` — что мы последний раз сообщили радио о воспроизведении.
    По нему и узнаём, наш ли сейчас звук: радио шлёт «играть», когда
    владелец выбрал CD, и «стоп», когда ушёл на другой источник.
    """

    function: int = FUNC_NOT_PLAYING
    last_poll: float | None = None
    announced: bool = False

    @property
    def playing(self) -> bool:
        """Радио слушает нас: источник CD выбран и не на паузе."""
        return self.function in (FUNC_PLAYING, FUNC_SCAN, FUNC_RANDOM)

    def on_frame(self, frame: Frame, now: float) -> Answer:
        if frame.dst != CDC or frame.src != RADIO:
            return Answer()
        self.last_poll = now
        if frame.data[0] == POLL:
            return Answer([pong()])
        if frame.data[0] != REQUEST or len(frame.data) < 2:
            return Answer()
        cmd = frame.data[1]
        arg = frame.data[2] if len(frame.data) > 2 else 0
        return self._request(cmd, arg)

    def tick(self, now: float) -> list[Frame]:
        """Объявиться, если радио про нас не знает или забыло."""
        if not self.announced:
            self.announced = True
            self.last_poll = now
            return [announce()]
        if self.last_poll is not None and now - self.last_poll >= ANNOUNCE_AFTER:
            self.last_poll = now
            return [announce()]
        return []

    def reset(self) -> None:
        """Зажигание выключено: радио нас забудет, объявимся заново."""
        self.function = FUNC_NOT_PLAYING
        self.last_poll = None
        self.announced = False

    def _request(self, cmd: int, arg: int) -> Answer:
        track = None
        if cmd == CMD_STATUS:
            status = self._status_for(self.function)
        elif cmd == CMD_STOP:
            self.function = FUNC_NOT_PLAYING
            status = STAT_STOP
        elif cmd == CMD_PAUSE:
            self.function = FUNC_PAUSE
            status = STAT_PAUSE
        elif cmd == CMD_PLAY:
            self.function = FUNC_PLAYING
            status = STAT_PLAYING
        elif cmd in (CMD_TRACK, CMD_TRACK_ALT):
            # 00 — следующий, 01 — предыдущий.
            track = arg == 0x00
            status = STAT_PLAYING
        elif cmd == CMD_SEEK:
            # Перемотки внутри трека в протоколе донгла нет. Подтверждаем,
            # чтобы радио не повторяло, и больше ничего не делаем.
            status = STAT_FAST_REV
        elif cmd == CMD_DISC:
            self.function = FUNC_PLAYING
            status = STAT_PLAYING
        elif cmd in (CMD_SCAN, CMD_RANDOM):
            if arg == 0x01:
                self.function = FUNC_SCAN if cmd == CMD_SCAN else FUNC_RANDOM
            elif self.function in (FUNC_SCAN, FUNC_RANDOM):
                self.function = FUNC_PLAYING
            status = STAT_PLAYING
        else:
            # Незнакомая команда: так же, как BlueBus, повторяем её код
            # в байте состояния, чтобы радио получило хоть какой-то ответ.
            status = cmd
        return Answer([status_frame(status, self.function)], track=track)

    @staticmethod
    def _status_for(function: int) -> int:
        if function == FUNC_PAUSE:
            return STAT_PAUSE
        if function == FUNC_NOT_PLAYING:
            return STAT_STOP
        return STAT_PLAYING


def pong() -> Frame:
    return Frame(src=CDC, dst=RADIO, data=bytes([PONG, 0x00]))


def announce() -> Frame:
    return Frame(src=CDC, dst=BROADCAST, data=bytes([PONG, 0x01]))


def status_frame(status: int, function: int) -> Frame:
    """Короткий статус в семь байтов, как у заводского чейнджера.

    Status | Function | Error | Magazine | Aux | Disc | Track.
    Длинный вариант с MP3-полями, который шлёт BlueBus, нам не нужен:
    текста о треке мы радио всё равно не даём.
    """
    return Frame(
        src=CDC,
        dst=RADIO,
        data=bytes([STATUS, status, function, 0x00, MAGAZINE_ONE_DISC, 0x00, DISC, TRACK]),
    )

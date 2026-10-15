"""Питание малины на плате из docs/20: когда отпустить HOLD.

Ключ 12 В на плате открыт, если недавно был трафик на шине (детектор
заряжает C2) или если малина держит HOLD = 1 на GPIO26. Малина не делает
poweroff, а только отпускает HOLD при работающем Linux:

  шина молчит QUIET секунд  → Release: HOLD = 0
      шина правда спит      → C2 пустой, ключ закрывается, питание пропадает
      шина ожила            → C2 держит ключ, мы продолжаем работать
  прошло CONFIRM, а мы живы → Hold: HOLD = 1, следующая попытка через RETRY
  пришёл кадр после Release → Hold сразу, ждать незачем

Повтор нужен потому, что пока малина работает, C2 разряжается только через
R4 (2,2 МОм, 22 с). При худшем пороге Q2 он держит ключ до минуты после
последнего кадра, и первая попытка может не сработать.

Зажигание здесь не учитывается. Пока оно включено, шина не молчит. А если
перестал отвечать наш приёмник, а шина жива, попытка безвредна: C2 заряжен
настоящим трафиком, ключ не закроется, и мы вернём HOLD.

Как и agent/state.py: только логика, время приходит снаружи.
"""

from __future__ import annotations

from dataclasses import dataclass

QUIET = 60.0     # тишина на шине, после которой машина считается спящей
CONFIRM = 3.0    # сколько ждать после Release, прежде чем признать, что не вышло
RETRY = 30.0     # пауза между попытками


@dataclass(frozen=True)
class Release:
    """HOLD = 0. Перед этим сбросить журналы на диск: питание может пропасть сразу."""


@dataclass(frozen=True)
class Hold:
    """HOLD = 1. `why` — для журнала."""

    why: str


PowerCommand = Release | Hold


@dataclass
class Power:
    last_frame: float
    released_at: float | None = None
    last_attempt: float | None = None

    @classmethod
    def start(cls, now: float) -> "Power":
        """Сразу после загрузки считаем, что кадр только что был: нас разбудила шина."""
        return cls(last_frame=now)

    @property
    def releasing(self) -> bool:
        return self.released_at is not None

    def on_frame(self, now: float) -> list[PowerCommand]:
        self.last_frame = now
        if self.releasing:
            self.released_at = None
            return [Hold("шина ожила, питание держим")]
        return []

    def tick(self, now: float) -> list[PowerCommand]:
        if self.releasing:
            if now - self.released_at >= CONFIRM:
                self.released_at = None
                return [Hold("питание не пропало, C2 ещё держит ключ")]
            return []
        if now - self.last_frame < QUIET:
            return []
        if self.last_attempt is not None and now - self.last_attempt < RETRY:
            return []
        self.released_at = now
        self.last_attempt = now
        return [Release()]

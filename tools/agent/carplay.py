"""Связь с CarPlay. Пока заглушка, но с настоящим интерфейсом.

Разбор USB-протокола донгла Carlinkit живёт в node-CarPlay и появится здесь
позже. Чтобы не ждать его, автомат состояний разговаривает с backend'ом через
эти три метода, а заглушка просто пишет в лог. Когда появится настоящий
backend, менять придётся только этот файл.
"""

from __future__ import annotations

from typing import Protocol

from .logs import setup


class Backend(Protocol):
    def navigate(self, right: bool, steps: int) -> None: ...
    def select(self) -> None: ...
    def back(self) -> None: ...
    def track(self, forward: bool) -> None: ...
    def connected(self) -> bool: ...


class LogBackend:
    """Заглушка: ничего не делает, только сообщает, что её позвали.

    `phone` задаётся снаружи и позволяет на стенде изобразить подключение
    телефона, пока настоящего донгла в схеме нет.
    """

    def __init__(self, phone: bool = False) -> None:
        self.phone = phone
        self.calls: list[str] = []

    def navigate(self, right: bool, steps: int) -> None:
        self._note(f"CarPlay: {'вправо' if right else 'влево'} на {steps}")

    def select(self) -> None:
        self._note("CarPlay: выбор")

    def back(self) -> None:
        self._note("CarPlay: назад")

    def track(self, forward: bool) -> None:
        self._note(f"CarPlay: {'следующий' if forward else 'предыдущий'} трек")

    def connected(self) -> bool:
        return self.phone

    def _note(self, text: str) -> None:
        self.calls.append(text)
        setup("agent").info(text)

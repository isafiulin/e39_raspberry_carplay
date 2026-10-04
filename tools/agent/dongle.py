"""Связь с процессом, который держит сеанс CarPlay.

Разделение простое и намеренное: **мозг здесь, а не там**. Тот процесс только
разговаривает с донглом, показывает картинку и играет звук. Решения — какую
кнопку куда, показывать или прятать — принимает автомат в `state.py`, который
покрыт тестами. Поэтому замена библиотеки донгла или переезд на другой язык
не заденут логику.

Протокол — строки JSON, по одной на строку, через локальный сокет.

    мы туда   {"cmd": "navigate", "right": true, "steps": 1}
              {"cmd": "select"}
              {"cmd": "back"}

    нам оттуда {"event": "phone", "connected": true}

Сокет может быть ещё не поднят: тогда бэкенд молча ждёт и переподключается сам.
Сервис из-за этого не падает и не зависает — телефон просто считается
неподключённым, а это ровно то состояние, в котором мы ничего не показываем.
"""

from __future__ import annotations

import json
import socket
import threading
import time

DEFAULT_PATH = "/tmp/carplay.sock"
RECONNECT_SECONDS = 2.0


class DongleBackend:
    """Клиент к процессу CarPlay. Переподключается сам, наружу не бросает."""

    def __init__(self, path: str = DEFAULT_PATH, *, reconnect: float = RECONNECT_SECONDS) -> None:
        self.path = path
        self.reconnect = reconnect
        self._lock = threading.Lock()
        self._sock: socket.socket | None = None
        self._connected = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="carplay", daemon=True)
        self._thread.start()

    # --- то, чего ждёт от нас автомат ---------------------------------------

    def navigate(self, right: bool, steps: int) -> None:
        self._send({"cmd": "navigate", "right": right, "steps": steps})

    def select(self) -> None:
        self._send({"cmd": "select"})

    def back(self) -> None:
        self._send({"cmd": "back"})

    def track(self, forward: bool) -> None:
        self._send({"cmd": "next" if forward else "prev"})

    def connected(self) -> bool:
        """Есть ли телефон. Пока сокета нет — False, и это правильный ответ."""
        return self._connected

    # --- жизнь соединения ----------------------------------------------------

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            if self._sock is not None:
                self._sock.close()
                self._sock = None
        self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        buffer = b""
        while not self._stop.is_set():
            if self._sock is None:
                if not self._connect():
                    self._stop.wait(self.reconnect)
                    continue
                buffer = b""
            try:
                chunk = self._sock.recv(4096)  # type: ignore[union-attr]
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                self._drop()
                continue
            if not chunk:
                self._drop()
                continue
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                self._on_line(line)

    def _connect(self) -> bool:
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            sock.connect(self.path)
        except OSError:
            return False
        with self._lock:
            self._sock = sock
        return True

    def _drop(self) -> None:
        with self._lock:
            if self._sock is not None:
                self._sock.close()
                self._sock = None
        # Соединение пропало — значит про телефон мы больше ничего не знаем.
        # Считать, что он на месте, опаснее: останемся с картинкой на экране.
        self._connected = False

    def _on_line(self, line: bytes) -> None:
        try:
            message = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return
        if message.get("event") == "phone":
            self._connected = bool(message.get("connected"))

    def _send(self, message: dict) -> None:
        raw = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            sock = self._sock
        if sock is None:
            return
        try:
            sock.sendall(raw)
        except OSError:
            self._drop()


def wait_connected(backend: DongleBackend, timeout: float = 3.0) -> bool:
    """Подождать появления сокета. Нужно только в тестах и при отладке."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with backend._lock:
            if backend._sock is not None:
                return True
        time.sleep(0.02)
    return False

"""Связь с процессом CarPlay. Настоящий сокет, поддельный собеседник.

Проверяем то, что будет ломаться в жизни: процесса ещё нет, процесс упал,
процесс прислал мусор.
"""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from agent.dongle import DongleBackend, wait_connected


class FakeCarPlay:
    """Изображает процесс, который держит донгл."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.received: list[dict] = []
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(path)
        self._server.listen(1)
        self._server.settimeout(3.0)
        self._client: socket.socket | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def wait_client(self, timeout: float = 3.0) -> bool:
        """Дождаться, пока соединение действительно принято.

        Без этого тест изредка падал: мы писали клиенту раньше, чем поток
        приёма успевал его принять, и сообщение пропадало.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._client is not None:
                return True
            time.sleep(0.02)
        return False

    def say_phone(self, connected: bool) -> None:
        self._write({"event": "phone", "connected": connected})

    def drop(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def close(self) -> None:
        self._stop.set()
        self.drop()
        self._server.close()

    def _loop(self) -> None:
        try:
            self._client, _ = self._server.accept()
        except OSError:
            return
        self._client.settimeout(0.2)
        buffer = b""
        while not self._stop.is_set() and self._client is not None:
            try:
                chunk = self._client.recv(4096)
            except (TimeoutError, socket.timeout):
                continue
            except OSError:
                return
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                self.received.append(json.loads(line))

    def _write(self, message: dict) -> None:
        if self._client is not None:
            self._client.sendall((json.dumps(message) + "\n").encode())


@pytest.fixture
def pair(tmp_path):
    path = str(tmp_path / "carplay.sock")
    server = FakeCarPlay(path)
    backend = DongleBackend(path, reconnect=0.05)
    assert wait_connected(backend), "бэкенд не дождался сокета"
    assert server.wait_client(), "поддельный процесс не принял соединение"
    yield server, backend
    backend.close()
    server.close()


def eventually(predicate, timeout=2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_bez_sokseta_telefon_schitaetsya_otklyuchennym(tmp_path):
    # Процесс CarPlay ещё не поднялся. Это не ошибка: просто ничего не показываем.
    backend = DongleBackend(str(tmp_path / "net.sock"), reconnect=0.05)
    try:
        assert backend.connected() is False
    finally:
        backend.close()


def test_uznayom_o_telefone(pair):
    server, backend = pair
    server.say_phone(True)
    assert eventually(lambda: backend.connected() is True)
    server.say_phone(False)
    assert eventually(lambda: backend.connected() is False)


def test_komandy_dohodyat(pair):
    server, backend = pair
    backend.navigate(right=True, steps=2)
    backend.select()
    backend.back()
    assert eventually(lambda: len(server.received) == 3)
    assert server.received == [
        {"cmd": "navigate", "right": True, "steps": 2},
        {"cmd": "select"},
        {"cmd": "back"},
    ]


def test_obryv_svyazi_snimaet_telefon(pair):
    # Если процесс упал, считать телефон подключённым опаснее: останемся
    # с картинкой на экране и без управления.
    server, backend = pair
    server.say_phone(True)
    assert eventually(lambda: backend.connected() is True)
    server.drop()
    assert eventually(lambda: backend.connected() is False)


def test_musor_ne_valit_servis(pair):
    server, backend = pair
    server._write({"event": "чушь"})
    if server._client is not None:
        server._client.sendall("не json\n".encode())
    server.say_phone(True)
    assert eventually(lambda: backend.connected() is True)

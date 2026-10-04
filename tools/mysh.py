#!/usr/bin/env python3
"""Мышь как палец: превращает клики на экране в касания CarPlay.

Нужно только для стенда. В машине ни мыши, ни касаний не будет — там
управление крутилкой и кнопками. Но пока идёт отладка, тыкать мышкой
в интерфейс куда быстрее, чем крутить вслепую.

Как устроено:

* кнопки мыши читаем **прямо из ядра**, из /dev/input. Через `xinput` пробовали
  и отказались: он молчал даже тогда, когда ядро выдавало десятки килобайт
  событий, а клики в системе работали;
* положение курсора спрашиваем у самого X через `XQueryPointer` из libX11,
  вызывая её напрямую через ctypes. Ни xdotool, ни python-xlib не нужны;
* координаты пересчитываем в доли от картинки CarPlay и отправляем процессу
  CarPlay по тому же сокету, что и остальные команды.

Картинка CarPlay обычно не совпадает по пропорциям с экраном, и вокруг неё
остаются чёрные поля. Их надо вычесть, иначе палец будет попадать мимо.

    DISPLAY=:0 XAUTHORITY=$HOME/.Xauthority python3 mysh.py
    ... --ekran 720x576 --kartinka 800x480
"""

from __future__ import annotations

import argparse
import ctypes
import glob
import json
import os
import socket
import struct
import sys
import time

SOCKET = "/tmp/carplay.sock"

# struct input_event: два поля времени машинного слова, тип, код, значение.
EVENT_FORMAT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

EV_KEY = 0x01
EV_REL = 0x02
BTN_LEFT = 0x110

MOTION_MIN_INTERVAL = 0.03  # не чаще тридцати раз в секунду


class Pointer:
    """Положение указателя из X, через libX11 напрямую."""

    def __init__(self) -> None:
        self.lib = ctypes.CDLL("libX11.so.6")
        self.lib.XOpenDisplay.restype = ctypes.c_void_p
        self.lib.XDefaultRootWindow.restype = ctypes.c_ulong
        self.lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        display = os.environ.get("DISPLAY", ":0").encode()
        self.display = self.lib.XOpenDisplay(display)
        if not self.display:
            raise RuntimeError(f"не открыть дисплей {display.decode()}")
        self.root = self.lib.XDefaultRootWindow(self.display)

    def position(self) -> tuple[int, int]:
        root_ret = ctypes.c_ulong()
        child_ret = ctypes.c_ulong()
        root_x = ctypes.c_int()
        root_y = ctypes.c_int()
        win_x = ctypes.c_int()
        win_y = ctypes.c_int()
        mask = ctypes.c_uint()
        self.lib.XQueryPointer(
            ctypes.c_void_p(self.display), ctypes.c_ulong(self.root),
            ctypes.byref(root_ret), ctypes.byref(child_ret),
            ctypes.byref(root_x), ctypes.byref(root_y),
            ctypes.byref(win_x), ctypes.byref(win_y), ctypes.byref(mask),
        )
        return root_x.value, root_y.value


class Screen:
    """Пересчёт координат экрана в доли картинки CarPlay.

    Картинка вписана в экран с сохранением пропорций и отцентрована, поэтому
    сверху и снизу либо слева и справа остаются поля. Точки, попавшие в поля,
    отбрасываем: это не промах пальца, а клик мимо картинки.
    """

    def __init__(self, screen: tuple[int, int], picture: tuple[int, int]) -> None:
        sw, sh = screen
        pw, ph = picture
        scale = min(sw / pw, sh / ph)
        self.width = pw * scale
        self.height = ph * scale
        self.left = (sw - self.width) / 2
        self.top = (sh - self.height) / 2

    def to_fraction(self, x: float, y: float) -> tuple[float, float] | None:
        fx = (x - self.left) / self.width
        fy = (y - self.top) / self.height
        if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
            return None
        return fx, fy


def size(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"нужен размер вида 800x480: {exc}") from exc


def find_mouse() -> str | None:
    """Первое мышиное устройство ядра. Их бывает несколько на один грызун."""
    candidates = sorted(glob.glob("/dev/input/by-id/*-event-mouse"))
    for path in candidates:
        if os.access(path, os.R_OK):
            return path
    return candidates[0] if candidates else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Мышь как палец для CarPlay")
    parser.add_argument("--sokset", default=SOCKET)
    parser.add_argument("--ekran", type=size, default=(720, 576), help="размер экрана, например 720x576")
    parser.add_argument("--kartinka", type=size, default=(800, 480), help="размер картинки CarPlay")
    parser.add_argument("--ustroystvo", help="файл события мыши, иначе найдётся сам")
    args = parser.parse_args(argv)

    device = args.ustroystvo or find_mouse()
    if not device:
        print("Не нашёл мышь в /dev/input/by-id", file=sys.stderr)
        return 1

    screen = Screen(args.ekran, args.kartinka)
    print(f"Мышь: {device}", flush=True)
    print(f"Картинка занимает {screen.width:.0f}x{screen.height:.0f} с отступом "
          f"{screen.left:.0f}, {screen.top:.0f}. Клики мимо неё игнорирую.", flush=True)

    try:
        pointer = Pointer()
    except (OSError, RuntimeError) as exc:
        print(f"Не добраться до X: {exc}", file=sys.stderr)
        return 1

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(args.sokset)
    except OSError as exc:
        print(f"Не подключиться к {args.sokset}: {exc}. Процесс CarPlay запущен?", file=sys.stderr)
        return 1

    def send(action: str, fx: float, fy: float) -> None:
        line = json.dumps({"cmd": "touch", "action": action, "x": round(fx, 4), "y": round(fy, 4)})
        sock.sendall(line.encode() + b"\n")

    def touch(action: str) -> bool:
        point = screen.to_fraction(*pointer.position())
        if point is None:
            return False
        send(action, *point)
        if action != "move":
            print(f"  {action} в {point[0]:.3f}, {point[1]:.3f}", flush=True)
        return True

    pressed = False
    last_motion = 0.0
    print("Слушаю мышь. Ctrl+C чтобы остановить.", flush=True)
    try:
        with open(device, "rb", buffering=0) as stream:
            while True:
                raw = stream.read(EVENT_SIZE)
                if not raw or len(raw) < EVENT_SIZE:
                    continue
                _, _, ev_type, code, value = struct.unpack(EVENT_FORMAT, raw)
                if ev_type == EV_KEY and code == BTN_LEFT:
                    if value == 1:
                        pressed = touch("down")
                    elif value == 0 and pressed:
                        pressed = False
                        touch("up")
                elif ev_type == EV_REL and pressed:
                    now = time.monotonic()
                    if now - last_motion >= MOTION_MIN_INTERVAL:
                        last_motion = now
                        touch("move")
    except KeyboardInterrupt:
        print("\nОстановлено.")
    except PermissionError:
        print(f"Нет доступа к {device}. Нужна группа input.", file=sys.stderr)
        return 1
    finally:
        if pressed:
            send("up", 0.5, 0.5)
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

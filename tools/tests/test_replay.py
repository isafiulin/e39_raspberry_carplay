"""Разбор логов снифера. Проверяется на настоящем файле из logs/."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.replay import frames_from_log

LOG = Path(__file__).resolve().parents[2] / "logs" / "20260930-knopka-display.log"


@pytest.mark.skipif(not LOG.exists(), reason="лог не рядом, например запуск на малине")
def test_chitaem_nastoyashchiy_log():
    frames = list(frames_from_log(LOG))
    assert len(frames) > 50
    # В этом логе изолированно нажимали DISPLAY, значит кадр кнопки обязан быть.
    assert any(f.data[:2] == bytes([0x48, 0x30]) for f in frames)


def test_musornye_stroki_propuskayutsya(tmp_path):
    path = tmp_path / "log.txt"
    path.write_text(
        "Слушаю /dev/ttyUSB0. Ctrl+C чтобы остановить.\n"
        "   37.714  F0 04 68 48 30 E4                BMBT → RAD       48 30  кнопка\n"
        "   37.715  ZZ ZZ\n"
        "\n"
        "Поймано кадров: 107, сбоев разбора: 0\n",
        encoding="utf-8",
    )
    frames = list(frames_from_log(path))
    assert len(frames) == 1
    assert frames[0].data == bytes([0x48, 0x30])

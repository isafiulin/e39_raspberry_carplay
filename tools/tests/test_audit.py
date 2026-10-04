"""Регрессии аудита 29.09.2026: сейчас падают, железо не требуется.

Запуск из tools: .venv/bin/python -m pytest tests/test_audit.py -q
"""

from types import SimpleNamespace

from ibus import Frame, Parser, describe
from ibus.port import Bus
from radio_sim import KEYS


def test_partial_payload_is_not_a_separate_frame():
    inner = Frame(0x68, 0x18, b"\x01")
    outer = Frame(0x18, 0x68, b"\x39" + inner.to_bytes() + b"\xaa\xbb")
    raw = outer.to_bytes()
    parser = Parser()
    assert parser.feed(raw[:9]) + parser.feed(raw[9:]) == [outer]


def test_wait_idle_preserves_received_frame():
    frame = Frame(0x68, 0x18, b"\x01")
    incoming = bytearray(frame.to_bytes())
    # ponytail: только входной буфер; USB-тайминги проверяются на железе.
    port = SimpleNamespace(in_waiting=len(incoming))

    def read(size):
        chunk = bytes(incoming[:size])
        del incoming[:size]
        port.in_waiting = len(incoming)
        return chunk

    port.read = read
    bus = Bus(port, Parser())
    assert bus._wait_idle()
    assert bus.poll() == [frame]


def test_cdc_disc_and_track_fields():
    frame = Frame.parse(bytes.fromhex("18 0A 68 39 02 09 00 01 00 01 09 41"))
    assert describe(frame) == "чейнджер: диск 1, трек 9"


def test_next_release_is_not_previous_track():
    frame = Frame.parse(bytes.fromhex("50 04 68 3B 21 26"))
    assert "назад" not in describe(frame)


def test_mfl_volume_is_decoded():
    frame = Frame.parse(bytes.fromhex("50 04 68 32 11 1F"))
    assert describe(frame) is not None


def test_dial_preserves_fifth_step_bit():
    frame = Frame(0xF0, 0x3B, b"\x49\x10")
    assert describe(frame).endswith("на 16")


def test_simulator_sends_navigation_dial_to_gt():
    assert KEYS["l"][1].dst == KEYS["r"][1].dst == 0x3B

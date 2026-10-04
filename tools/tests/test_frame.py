"""Тесты кадров I-Bus. Запуск: python3 -m pytest tools/tests -q"""

from __future__ import annotations

import pytest

from ibus import Frame, FrameError, Parser, checksum, describe

# Кадры, выписанные из документации сообщества. Контрольные суммы
# в них настоящие, поэтому это заодно проверка нашей арифметики.
KNOWN = {
    "68 03 18 01 72": (0x68, 0x18, bytes([0x01])),
    "18 04 68 02 00 76": (0x18, 0x68, bytes([0x02, 0x00])),
    "18 04 FF 02 01 E0": (0x18, 0xFF, bytes([0x02, 0x01])),
    "ED 05 F0 4F 11 11 57": (0xED, 0xF0, bytes([0x4F, 0x11, 0x11])),
    "ED 05 F0 4F 12 11 54": (0xED, 0xF0, bytes([0x4F, 0x12, 0x11])),
    "3B 04 F0 4F 10 90": (0x3B, 0xF0, bytes([0x4F, 0x10])),
    "3B 04 F0 4F 00 80": (0x3B, 0xF0, bytes([0x4F, 0x00])),
}


def raw(text: str) -> bytes:
    return bytes(int(t, 16) for t in text.split())


@pytest.mark.parametrize("text,expected", KNOWN.items())
def test_parses_known_frames(text: str, expected: tuple[int, int, bytes]) -> None:
    frame = Frame.parse(raw(text))
    assert (frame.src, frame.dst, frame.data) == expected


@pytest.mark.parametrize("text", KNOWN)
def test_roundtrip(text: str) -> None:
    """Разобрали и собрали обратно — байты те же, включая контрольную сумму."""
    assert Frame.parse(raw(text)).to_bytes() == raw(text)


def test_checksum_is_xor_of_body() -> None:
    body = raw("68 03 18 01")
    assert checksum(body) == 0x72


def test_bad_checksum_rejected() -> None:
    with pytest.raises(FrameError, match="контрольная сумма"):
        Frame.parse(raw("68 03 18 01 73"))


def test_length_mismatch_rejected() -> None:
    with pytest.raises(FrameError, match="длина"):
        Frame.parse(raw("68 04 18 01 72"))


def test_too_short_rejected() -> None:
    with pytest.raises(FrameError, match="короткий"):
        Frame.parse(raw("68 03 18"))


def test_empty_data_rejected() -> None:
    with pytest.raises(FrameError, match="без данных"):
        Frame(src=0x68, dst=0x18, data=b"")


# --- потоковый разбор --------------------------------------------------------


def test_parser_splits_back_to_back_frames() -> None:
    stream = raw("68 03 18 01 72") + raw("18 04 68 02 00 76")
    frames = Parser().feed(stream)
    assert [f.src for f in frames] == [0x68, 0x18]


def test_parser_waits_for_the_rest() -> None:
    parser = Parser()
    assert parser.feed(raw("68 03 18")) == []
    frames = parser.feed(raw("01 72"))
    assert len(frames) == 1 and frames[0].dst == 0x18


def test_parser_recovers_after_garbage() -> None:
    """Мусор в начале потока не должен глушить последующие кадры."""
    parser = Parser()
    frames = parser.feed(raw("AA BB") + raw("68 03 18 01 72"))
    assert len(frames) == 1
    assert frames[0].src == 0x68
    assert parser.resyncs > 0
    assert parser.lost_bytes == 2


def test_parser_waits_instead_of_guessing_inside_payload() -> None:
    """Пока кадр может ещё прийти, разборщик не ищет начало внутри данных.

    Иначе один и тот же поток разбирался бы по-разному в зависимости от
    того, как его нарезали чтения порта.
    """
    parser = Parser()
    assert parser.feed(raw("68 03 18 FF") + raw("18 04 68 02 00 76")) == []


def test_recover_pulls_the_frame_out_of_debris() -> None:
    """После паузы в линии обрывок выбрасывается, а целый кадр забирается."""
    parser = Parser()
    parser.feed(raw("68 03 18 FF") + raw("18 04 68 02 00 76"))
    frames = parser.recover()
    assert [(f.src, f.dst) for f in frames] == [(0x18, 0x68)]
    assert parser.lost_bytes > 0


def test_recover_on_hopeless_buffer_clears_it() -> None:
    parser = Parser()
    parser.feed(raw("AA BB CC DD EE FF"))
    assert parser.recover() == []
    assert parser.buffer == bytearray()


def test_flush_drops_partial_tail() -> None:
    parser = Parser()
    parser.feed(raw("68 03 18"))
    parser.flush()
    assert parser.feed(raw("18 04 68 02 00 76"))[0].src == 0x18


# --- расшифровка -------------------------------------------------------------


def test_describes_changer_poll() -> None:
    assert "чейнджер" in describe(Frame.parse(raw("68 03 18 01 72")))


def test_describes_monitor_tv_mode() -> None:
    # 11 = включён + источник TV, 12 = 16:9 + показывает вход AV/TV
    text = describe(Frame.parse(raw("ED 05 F0 4F 11 12 54")))
    assert "TV" in text and "16:9" in text and "вход AV" in text


def test_describes_monitor_nav_mode() -> None:
    # 10 = включён + источник навигации
    text = describe(Frame.parse(raw("ED 05 F0 4F 10 12 55")))
    assert "навигация" in text


def test_describes_monitor_ntsc() -> None:
    # Младшие биты второго байта следуют за тем, что модуль выводит:
    # 11 видели на задней передаче, 12 при показе AV. Проверено в машине 30.09.2026.
    assert "камер" in describe(Frame.parse(raw("ED 05 F0 4F 11 11 57")))


def test_monitor_power_off() -> None:
    assert "выключен" in describe(Frame.parse(raw("3B 04 F0 4F 00 80")))


def test_unknown_frame_has_no_description() -> None:
    assert describe(Frame(src=0x11, dst=0x22, data=bytes([0x99]))) is None

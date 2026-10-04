"""Эмулятор чейнджера, вариант 2. Пока не используется, но проверяется.

Ожидаемые кадры взяты из примеров wilhelm-docs (cdc/38.md, cdc/39.md),
запрос статуса — из нашего лога 30.09.2026.
"""

from __future__ import annotations

from agent.cdc import CdcAudio
from agent.state import Track
from ibus import Frame
from ibus.cdc import ANNOUNCE_AFTER, Changer


def frame(text: str) -> Frame:
    return Frame.parse(bytes.fromhex(text.replace(" ", "")))


POLL = "68 03 18 01 72"
STATUS_REQUEST = "68 05 18 38 00 00 4D"  # есть в logs/, радио ищет чейнджер
STOP = "68 05 18 38 01 00 4C"
PAUSE = "68 05 18 38 02 00 4F"
PLAY = "68 05 18 38 03 00 4E"
NEXT = "68 05 18 38 0A 00 47"
PREV = "68 05 18 38 0A 01 46"
IGNITION_OFF = "80 04 BF 11 00 2A"
BUTTON_DISPLAY = "F0 04 68 48 30 E4"


def test_otvechaet_na_opros():
    answer = Changer().on_frame(frame(POLL), 0.0)
    assert [f.hex() for f in answer.frames] == ["18 04 68 02 00 76"]


def test_obyavlyaetsya_pri_starte_odin_raz():
    c = Changer()
    assert [f.hex() for f in c.tick(0.0)] == ["18 04 FF 02 01 E0"]
    assert c.tick(1.0) == []


def test_obyavlyaetsya_zanovo_esli_radio_zabylo():
    c = Changer()
    c.tick(0.0)
    c.on_frame(frame(STATUS_REQUEST), 5.0)
    assert c.tick(5.0 + ANNOUNCE_AFTER - 1) == []
    assert len(c.tick(5.0 + ANNOUNCE_AFTER)) == 1


def test_status_po_formatu_zavodskogo():
    # Формат как у 18 0A 68 39 02 09 00 3F 00 01 01 из wilhelm, но диск один.
    c = Changer()
    c.on_frame(frame(PLAY), 0.0)
    answer = c.on_frame(frame(STATUS_REQUEST), 1.0)
    assert [f.hex() for f in answer.frames] == ["18 0A 68 39 02 09 00 01 00 01 01 49"]


def test_igrat_i_stop_menyayut_nash_zvuk():
    c = Changer()
    assert not c.playing
    c.on_frame(frame(PLAY), 0.0)
    assert c.playing
    c.on_frame(frame(PAUSE), 1.0)
    assert not c.playing
    c.on_frame(frame(PLAY), 2.0)
    c.on_frame(frame(STOP), 3.0)
    assert not c.playing


def test_na_kazhduyu_komandu_est_otvet():
    c = Changer()
    for text in (STATUS_REQUEST, STOP, PAUSE, PLAY, NEXT, PREV, "68 05 18 38 0F 00 42"):
        assert len(c.on_frame(frame(text), 0.0).frames) == 1, text


def test_trek_vpered_i_nazad():
    c = Changer()
    assert c.on_frame(frame(NEXT), 0.0).track is True
    assert c.on_frame(frame(PREV), 0.0).track is False


def test_chuzhie_kadry_ne_trogaet():
    c = Changer()
    answer = c.on_frame(frame(BUTTON_DISPLAY), 0.0)
    assert answer.frames == [] and answer.track is None


def test_prosloyka_otdaet_trek_v_carplay():
    audio = CdcAudio()
    audio.on_frame(frame(PLAY), 0.0)
    assert audio.our_audio
    frames, commands = audio.on_frame(frame(NEXT), 1.0)
    assert len(frames) == 1
    assert commands == [Track(forward=True)]


def test_zazhiganie_sbrasyvaet_chejndzher():
    audio = CdcAudio()
    audio.tick(0.0)
    audio.on_frame(frame(PLAY), 0.0)
    audio.on_frame(frame(IGNITION_OFF), 1.0)
    assert not audio.our_audio
    # Следующая поездка: радио нас не знает, объявляемся сразу.
    assert len(audio.tick(2.0)) == 1

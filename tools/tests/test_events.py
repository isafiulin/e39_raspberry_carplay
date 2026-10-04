"""Разбор смысловых событий. Кадры настоящие, сняты с машины 30.09.2026.

Все они лежат в logs/ — если тест здесь падает, сначала загляните туда,
возможно, в машине действительно что-то другое.
"""

from __future__ import annotations

from ibus import Frame
from ibus.events import Button, Dial, Gear, Ignition, MonitorState, RadioText, Speed, event


def ev(text: str):
    return event(Frame.parse(bytes.fromhex(text.replace(" ", ""))))


def test_knopki_monitora():
    assert ev("F0 04 68 48 30 E4") == Button(code=0x30, action="нажата", name="display")
    assert ev("F0 04 68 48 B0 64") == Button(code=0x30, action="отпущена", name="display")
    assert ev("F0 04 68 48 23 F7") == Button(code=0x23, action="нажата", name="mode")
    assert ev("F0 04 FF 48 34 77") == Button(code=0x34, action="нажата", name="menu")
    assert ev("F0 04 3B 48 05 82") == Button(code=0x05, action="нажата", name="dial")
    # Сняты с машины 01.10.2026, пришли на замену крутилке.
    assert ev("F0 04 68 48 00 D4") == Button(code=0x00, action="нажата", name="vpravo")
    assert ev("F0 04 68 48 10 C4") == Button(code=0x10, action="нажата", name="vlevo")
    assert ev("F0 04 68 48 14 C0") == Button(code=0x14, action="нажата", name="dvoynaya")
    assert ev("F0 04 FF 48 07 44") == Button(code=0x07, action="нажата", name="chasy")
    # У SELECT своя команда 0x47 и лишний нулевой байт перед кодом.
    assert ev("F0 05 FF 47 00 0F 42") == Button(code=0x0F, action="нажата", name="select")
    assert ev("F0 05 FF 47 00 8F C2") == Button(code=0x0F, action="отпущена", name="select")


def test_neznakomaya_knopka_ne_teryaetsya():
    # Код нам незнаком, но событие всё равно должно появиться: иначе
    # мы не узнаем, что кнопку вообще нажали.
    got = ev("F0 04 68 48 20 F4")
    assert isinstance(got, Button) and got.name is None and got.pressed


def test_krutilka():
    assert ev("F0 04 3B 49 81 07") == Dial(right=True, steps=1)


def test_sostoyanie_monitora():
    # 11 экран у видеомодуля, 12 экран у GT. Проверено переключениями в машине.
    assert ev("ED 05 F0 4F 11 12 54").video_module_owns_screen is True
    assert ev("ED 05 F0 4F 12 11 54").video_module_owns_screen is False
    assert isinstance(ev("ED 05 F0 4F 11 11 57"), MonitorState)


def test_zazhiganie():
    assert ev("80 04 BF 11 00 2A") == Ignition(state="выключено")
    assert ev("80 04 BF 11 01 2B") == Ignition(state="Kl.R")


def test_skorost_i_oboroty():
    assert ev("80 05 BF 18 04 09 2F") == Speed(kmh=4, rpm=900)


def test_peredacha():
    assert ev("80 0A BF 13 00 11 00 00 00 00 14 23") == Gear(code=0x11, name="R")
    assert ev("80 0A BF 13 00 B1 00 00 00 00 14 83") == Gear(code=0xB1, name="P")


def test_radio_soobshchaet_istochnik():
    assert ev("68 12 3B 23 62 10 41 55 58 20 20 20 20 20 20 20 20 20 20 5C") == RadioText(text="AUX")
    got = ev("68 12 3B 23 62 10 4E 4F 20 54 41 50 45 20 20 20 20 20 20 31")
    assert got == RadioText(text="NO TAPE")


def test_neinteresnye_kadry_dayut_none():
    assert ev("68 05 18 38 00 00 4D") is None
    assert ev("3B 03 ED 01 D4") is None


def test_podpisi_dlya_cheloveka():
    assert str(ev("F0 04 68 48 30 E4")) == "кнопка display: нажата"
    assert str(ev("F0 04 68 48 20 F4")) == "кнопка код 20: нажата"
    assert str(ev("F0 04 3B 49 81 07")) == "крутилка: вправо на 1"
    assert str(ev("ED 05 F0 4F 11 12 54")) == "экран занят: видеомодуль"
    assert str(ev("80 0A BF 13 00 B1 00 00 00 00 14 83")) == "передача: P"

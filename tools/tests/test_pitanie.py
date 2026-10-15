"""Когда отпускать питание: автомат из agent/pitanie.py."""

from __future__ import annotations

from agent.pitanie import CONFIRM, QUIET, RETRY, Hold, Power, Release


def test_ne_otpuskaet_poka_shina_zhivaya():
    p = Power.start(0.0)
    for t in range(0, 300, 5):
        p.on_frame(float(t))
        assert p.tick(float(t) + 1) == []


def test_otpuskaet_posle_minuty_tishiny():
    p = Power.start(0.0)
    assert p.tick(QUIET - 0.1) == []
    assert p.tick(QUIET) == [Release()]


def test_kadr_sbrasyvaet_otschet():
    p = Power.start(0.0)
    p.on_frame(50.0)
    assert p.tick(QUIET + 1) == []
    assert p.tick(50.0 + QUIET) == [Release()]


def test_esli_zhivy_posle_otpuskaniya_derzhim_snova():
    p = Power.start(0.0)
    p.tick(QUIET)
    assert p.tick(QUIET + CONFIRM - 0.1) == []
    commands = p.tick(QUIET + CONFIRM)
    assert len(commands) == 1 and isinstance(commands[0], Hold)
    assert not p.releasing


def test_kadr_vo_vremya_otpuskaniya_derzhit_srazu():
    p = Power.start(0.0)
    p.tick(QUIET)
    commands = p.on_frame(QUIET + 0.5)
    assert len(commands) == 1 and isinstance(commands[0], Hold)
    assert p.tick(QUIET + CONFIRM + 1) == []


def test_povtor_ne_chashche_raz_v_RETRY():
    p = Power.start(0.0)
    p.tick(QUIET)
    p.tick(QUIET + CONFIRM)
    assert p.tick(QUIET + RETRY - 0.1) == []
    assert p.tick(QUIET + RETRY) == [Release()]


def test_posle_kadra_snova_zhdet_polnuyu_minutu():
    p = Power.start(0.0)
    p.tick(QUIET)
    p.on_frame(QUIET + 1)
    assert p.tick(QUIET + 1 + QUIET - 0.1) == []
    assert p.tick(QUIET + 1 + QUIET) == [Release()]

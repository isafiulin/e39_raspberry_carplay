"""Автомат состояний. Проверяется без машины и без порта.

Сценарии взяты из того, что подтверждено в машине 30.09.2026, и из
требований владельца: выйти в меню машины и вернуться обратно.
"""

from __future__ import annotations

from agent.state import Agent, HidePicture, Navigate, Select, ShowPicture
from ibus import Frame
from ibus.events import event


def ev(text: str):
    return event(Frame.parse(bytes.fromhex(text.replace(" ", ""))))


DISPLAY = "F0 04 68 48 30 E4"
DISPLAY_UP = "F0 04 68 48 B0 64"
MENU = "F0 04 FF 48 34 77"
DIAL_RIGHT = "F0 04 3B 49 81 07"
SELECT = "F0 04 3B 48 05 82"
IGNITION_OFF = "80 04 BF 11 00 2A"
SCREEN_TO_GT = "ED 05 F0 4F 12 11 54"


def test_telefon_pokazyvaet_kartinku():
    a = Agent()
    assert a.phone_connected(True) == [ShowPicture()]
    assert a.visible


def test_povtornoe_soobshchenie_nichego_ne_delaet():
    a = Agent()
    a.phone_connected(True)
    assert a.phone_connected(True) == []


def test_menu_otpuskaet_ekran():
    a = Agent()
    a.phone_connected(True)
    assert a.on_event(ev(MENU)) == [HidePicture()]
    assert not a.visible and a.hidden_by_user


def test_display_pereklyuchaet_tuda_i_obratno():
    a = Agent()
    a.phone_connected(True)
    assert a.on_event(ev(DISPLAY)) == [HidePicture()]
    assert a.on_event(ev(DISPLAY)) == [ShowPicture()]
    assert a.visible


def test_otpuskanie_knopki_ne_schitaetsya_vtorym_nazhatiem():
    # Иначе каждое нажатие срабатывало бы дважды и картинка мигала.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(DISPLAY))
    assert a.on_event(ev(DISPLAY_UP)) == []


def test_bez_telefona_display_nichego_ne_pokazyvaet():
    a = Agent()
    assert a.on_event(ev(DISPLAY)) == []


def test_krutilku_otdali_mashine():
    # В режиме AV видеомодуль подслушивает кадры крутилки и рисует поверх
    # нашей картинки своё меню. Помешать нечем, поэтому крутилку не трогаем.
    # Проверено в машине 01.10.2026.
    a = Agent()
    a.phone_connected(True)
    assert a.on_event(ev(DIAL_RIGHT)) == []
    assert a.on_event(ev(SELECT)) == []


def test_telefon_propal_ekran_vozvrashchaetsya():
    a = Agent()
    a.phone_connected(True)
    assert a.phone_connected(False) == [HidePicture()]


def test_zazhiganie_sbrasyvaet_pamyat():
    # Модуль сбрасывается сам, проверено в машине. Нам важно не остаться
    # с ложным «картинка показана», иначе первое нажатие DISPLAY уйдёт впустую.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(IGNITION_OFF))
    assert not a.visible


def test_kartinku_snyali_mimo_nas():
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(SCREEN_TO_GT))
    assert not a.visible


def test_menu_kogda_nichego_ne_pokazano_molchit():
    a = Agent()
    assert a.on_event(ev(MENU)) == []


def test_uderzhanie_strelki_ignoriruem_vsegda():
    # Удержание стрелки — штатная перемотка. В протоколе донгла такой
    # команды нет, в CarPlay перемотка делается через полосу прогресса.
    a = Agent()
    a.phone_connected(True)
    assert a.on_event(ev("F0 04 68 48 50 84")) == []


def test_ubrannaya_vruchnuyu_ne_vyprygivaet_obratno():
    # Владелец ушёл в меню машины. Телефон моргнул Wi-Fi и вернулся.
    # Выдёргивать владельца из меню нельзя: вернуть картинку — его решение.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(MENU))
    assert a.phone_connected(False) == []
    assert a.phone_connected(True) == []
    assert not a.visible
    # Но кнопкой он её вернёт когда захочет.
    assert a.on_event(ev(DISPLAY)) == [ShowPicture()]


def test_telefon_propal_sam_i_vernulsya_kartinka_est():
    # Здесь владелец ничего не убирал, значит показать — правильно.
    a = Agent()
    a.phone_connected(True)
    assert a.phone_connected(False) == [HidePicture()]
    assert a.phone_connected(True) == [ShowPicture()]


AUX = "68 12 3B 23 62 10 41 55 58 20 20 20 20 20 20 20 20 20 20 5C"
RADIO = "68 12 3B 23 62 10 03 31 30 31 2E 33 04 20 4D 48 7A 20 20 65"
RUL_VPERED = "50 04 68 3B 01 06"
RUL_NAZAD = "50 04 68 3B 08 0F"
RUL_VPERED_OTPUSK = "50 04 68 3B 21 26"


def test_rul_pereklyuchaet_treki():
    from agent.state import Track
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(AUX))
    assert a.on_event(ev(RUL_VPERED)) == [Track(forward=True)]
    assert a.on_event(ev(RUL_NAZAD)) == [Track(forward=False)]


def test_rul_rabotaet_i_kogda_carplay_skryt():
    # Музыка играет, даже когда на экране меню машины. Треки должны
    # переключаться и в этом случае.
    from agent.state import Track
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(AUX))
    a.on_event(ev(MENU))
    assert not a.visible
    assert a.on_event(ev(RUL_VPERED)) == [Track(forward=True)]


def test_pri_radio_rul_do_telefona_ne_dohodit():
    # Слушают радио — значит «вперёд» на руле должна переключать станцию,
    # а не трек в телефоне. Помешать этому хуже, чем не переключить трек.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(RADIO))
    assert a.on_event(ev(RUL_VPERED)) == []


def test_poka_istochnik_neizvesten_rul_molchit():
    a = Agent()
    a.phone_connected(True)
    assert a.on_event(ev(RUL_VPERED)) == []


def test_otpuskanie_knopki_rulya_ne_schitaetsya():
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(AUX))
    assert a.on_event(ev(RUL_VPERED_OTPUSK)) == []


VPRAVO = "F0 04 68 48 00 D4"
VLEVO = "F0 04 68 48 10 C4"
DVOYNAYA = "F0 04 68 48 14 C0"
CHASY = "F0 04 FF 48 07 44"
MODE = "F0 04 68 48 23 F7"
TONE = "F0 04 68 48 04 D0"
SELECT_KNOPKA = "F0 05 FF 47 00 0F 42"


def test_strelki_monitora_eto_navigatsiya():
    # Вместо крутилки: нижняя пара стрелок монитора. Кадры сняты с машины.
    a = Agent()
    a.phone_connected(True)
    assert a.on_event(ev(VPRAVO)) == [Navigate(right=True, steps=1)]
    assert a.on_event(ev(VLEVO)) == [Navigate(right=False, steps=1)]


def test_select_eto_vybor():
    # У SELECT своя команда 0x47, а не 0x48 как у остальных кнопок.
    # Из-за этого мы её сначала сочли немой. Снято с машины 01.10.2026.
    a = Agent()
    a.phone_connected(True)
    assert a.on_event(ev(SELECT_KNOPKA)) == [Select()]


def test_tone_eto_nazad():
    from agent.state import Back
    a = Agent()
    a.phone_connected(True)
    assert a.on_event(ev(TONE)) == [Back()]


def test_dvoynaya_i_chasy_ostavleny_mashine():
    a = Agent()
    a.phone_connected(True)
    assert a.on_event(ev(CHASY)) == []
    assert a.on_event(ev(DVOYNAYA)) == []


def test_navigatsiya_molchit_pri_skrytom_carplay():
    # CarPlay убран, кнопки принадлежат машине.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(MENU))
    assert a.on_event(ev(VPRAVO)) == []
    assert a.on_event(ev(SELECT_KNOPKA)) == []
    assert a.on_event(ev(TONE)) == []


def test_pri_podklyuchenii_ishchem_aux():
    from agent.state import PressMode
    a = Agent()
    a.on_event(ev(RADIO))          # источник известен, значит есть обратная связь
    a.phone_connected(True)
    assert a.want_aux
    # Первое нажатие уходит сразу, следующее только после паузы.
    assert a.tick(100.0) == [PressMode()]
    assert a.tick(100.5) == []
    assert a.tick(102.0) == [PressMode()]


def test_uvidev_aux_perestayom_iskat():
    a = Agent()
    a.on_event(ev(RADIO))
    a.phone_connected(True)
    a.tick(100.0)
    a.on_event(ev(AUX))
    assert not a.want_aux
    assert a.tick(200.0) == []


def test_esli_aux_uzhe_vybran_ne_ishchem():
    a = Agent()
    a.on_event(ev(AUX))
    a.phone_connected(True)
    assert not a.want_aux
    assert a.tick(100.0) == []


def test_svoyo_nazhatie_ne_putaem_s_vladeltsem():
    # Наш кадр MODE вернётся с шины и будет выглядеть как нажатие владельцем.
    # Если спутать, перебор оборвётся на первом же шаге.
    from agent.state import PressMode
    a = Agent()
    a.on_event(ev(RADIO))
    a.phone_connected(True)
    assert a.tick(100.0) == [PressMode()]
    a.on_event(ev(MODE))
    assert a.want_aux, "своё нажатие не должно отменять поиск"
    assert a.tick(102.0) == [PressMode()]


def test_nazhatie_vladeltsa_otmenyaet_poisk():
    a = Agent()
    a.on_event(ev(RADIO))
    a.phone_connected(True)
    a.on_event(ev(MODE))
    assert not a.want_aux


def test_perebor_ne_beskonechnyy():
    a = Agent()
    a.on_event(ev(RADIO))
    a.phone_connected(True)
    for i in range(20):
        a.tick(100.0 + i * 2)
    assert not a.want_aux
    assert a.aux_attempts <= 8


ZVUK_ZABRALI = "3B 05 68 4E 01 00 19"
ZVUK_VERNULI = "3B 05 68 4E 00 00 18"


def test_vozvrashchaem_zvuk_kogda_ego_zabral_monitor():
    # Владелец вошёл в AV через меню монитора: тот отдельной командой
    # забрал звук, и CarPlay стал виден, но не слышен.
    from agent.state import LeaveTelevision
    a = Agent()
    a.phone_connected(True)
    assert a.on_event(ev(ZVUK_ZABRALI)) == [LeaveTelevision()]


def test_bez_telefona_zvuk_ne_otbiraem_obratno():
    a = Agent()
    assert a.on_event(ev(ZVUK_ZABRALI)) == []


def test_ne_ustraivaem_perebranku_s_monitorom():
    # Если монитор упрётся, лучше остаться без звука, чем молотить по шине.
    from agent.state import LeaveTelevision
    a = Agent()
    a.phone_connected(True)
    for _ in range(3):
        assert a.on_event(ev(ZVUK_ZABRALI)) == [LeaveTelevision()]
    assert a.on_event(ev(ZVUK_ZABRALI)) == []


def test_posle_vozvrata_schetchik_sbrasyvaetsya():
    from agent.state import LeaveTelevision
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(ZVUK_ZABRALI))
    a.on_event(ev(ZVUK_VERNULI))
    assert a.on_event(ev(ZVUK_ZABRALI)) == [LeaveTelevision()]


EKRAN_AV = "ED 05 F0 4F 11 12 54"
EKRAN_NAVIGATSIYA = "ED 05 F0 4F 12 11 54"
EKRAN_KAMERA = "ED 05 F0 4F 11 11 57"


def test_kartinku_vklyuchili_mimo_nas():
    # Владелец вошёл в AV через меню монитора. Если этого не заметить,
    # кнопки не будут передаваться в CarPlay, и выглядит это так, будто
    # управление забрало радио. Случилось в машине 02.10.2026.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(MENU))
    assert not a.visible
    a.on_event(ev(EKRAN_AV))
    assert a.visible, "модуль сказал, что показывает AV — значит показывает"
    assert a.on_event(ev(VPRAVO)) == [Navigate(right=True, steps=1)]


def test_kartinku_snyali_mimo_nas():
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(EKRAN_NAVIGATSIYA))
    assert not a.visible
    assert a.on_event(ev(VPRAVO)) == []


def test_kamera_eto_ne_nash_ekran():
    # При задней передаче экран занят модулем, но CarPlay там не видно.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(EKRAN_AV))
    a.on_event(ev(EKRAN_KAMERA))
    assert not a.visible
    assert a.on_event(ev(VPRAVO)) == []


def test_vozvrashchaem_ekran_kogda_ego_zabralo_radio():
    # Кнопки нижней пары адресованы радио. Получив нажатие, оно выводит свою
    # заставку, модуль уступает экран, и CarPlay пропадает. Проверено
    # в машине 02.10.2026.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(EKRAN_AV))
    assert a.visible
    assert a.on_event(ev(EKRAN_NAVIGATSIYA)) == [ShowPicture()]


def test_ne_vozvrashchaem_ekran_esli_ubrali_sami():
    # Владелец нажал MENU и ушёл в меню машины. Выдёргивать его обратно нельзя.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(EKRAN_AV))
    a.on_event(ev(MENU))
    assert a.on_event(ev(EKRAN_NAVIGATSIYA)) == []


def test_ne_speshim_s_kameroy():
    # При задней передаче экран занят модулем, просто показывает не нас.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(EKRAN_AV))
    assert a.on_event(ev(EKRAN_KAMERA)) == []


def test_odna_popytka_na_odnu_propazhu():
    # Если вернуть экран не удалось, второй попытки подряд не делаем:
    # перебранка с машиной хуже, чем отсутствие картинки. Новая попытка
    # будет, только когда картинка появится снова.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(EKRAN_AV))
    assert a.on_event(ev(EKRAN_NAVIGATSIYA)) == [ShowPicture()]
    assert a.on_event(ev(EKRAN_NAVIGATSIYA)) == [], "второй раз подряд не пробуем"
    a.on_event(ev(EKRAN_AV))
    assert a.on_event(ev(EKRAN_NAVIGATSIYA)) == [ShowPicture()], "после возврата снова пробуем"


def test_ne_perebiraem_vslepuyu():
    # Пока радио ни разу не сообщило источник, обратной связи нет. Перебор
    # вслепую однажды оставил источник на TV вместо AUX — 02.10.2026.
    a = Agent()
    a.phone_connected(True)
    assert not a.want_aux, "без обратной связи перебор не начинаем"
    assert a.tick(100.0) == []


def test_ishchem_kogda_istochnik_izvesten():
    from agent.state import PressMode
    a = Agent()
    a.on_event(ev(RADIO))          # радио сообщило: играет FM
    a.phone_connected(True)
    assert a.want_aux
    assert a.tick(100.0) == [PressMode()]


def test_posle_mode_ustupaem_ekran_radio():
    # Иначе владелец не увидит, какой источник выбрался, а мы не прочитаем
    # надпись радио — она наша единственная обратная связь по звуку.
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(EKRAN_AV))
    a.tick(100.0)
    a.on_event(ev(MODE))
    assert a.on_event(ev(EKRAN_NAVIGATSIYA)) == [], "сразу не отбираем"
    assert a.tick(101.0) == [], "и через секунду ещё рано"
    assert a.tick(105.0) == [ShowPicture()], "а через несколько секунд возвращаем"


def test_esli_kartinka_vernulas_sama_ne_trogaem():
    a = Agent()
    a.phone_connected(True)
    a.on_event(ev(EKRAN_AV))
    a.tick(100.0)
    a.on_event(ev(MODE))
    a.on_event(ev(EKRAN_NAVIGATSIYA))
    a.on_event(ev(EKRAN_AV))
    assert a.tick(105.0) == []

"""Автомат состояний: что делать, когда на шине что-то произошло.

Здесь нет ни порта, ни сети, ни сна — только чистая логика, поэтому её
можно целиком проверить тестами и не заводить машину.

Правила взяты из проверок в машине 30.09.2026:

* Картинкой командуем сами, звук не трогаем вообще: он живёт на AUX в стерео
  и не прерывается. Отдельная звуковая команда монитора нам не нужна.
* Пока наша картинка на экране, MENU и DISPLAY не делают ничего сами.
  Значит их обязаны обработать мы, иначе владелец не попадёт в настройки машины.
* Задняя передача обрабатывается железом: камера перебивает картинку,
  после паркинга она возвращается сама. Нам делать нечего.
* Цикл зажигания сбрасывает модуль сам. Нам остаётся забыть своё состояние.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ibus.events import AudioToTv, Button, Dial, Event, Gear, Ignition, MonitorState, RadioText, Speed, Steering

AUX_MAX_ATTEMPTS = 8
AUDIO_RETURN_LIMIT = 3  # попыток вернуть звук подряд
SCREEN_RETURN_LIMIT = 3  # попыток вернуть себе экран подряд
RADIO_SCREEN_SECONDS = 4.0  # сколько держать экран радио после нажатия MODE
AUX_PRESS_INTERVAL = 1.5  # секунды между нажатиями: радио успевает ответить


# --- что автомат просит сделать ----------------------------------------------


@dataclass(frozen=True)
class ShowPicture:
    """Показать нашу картинку: кадр 3B 05 BB 4F 01 00."""


@dataclass(frozen=True)
class HidePicture:
    """Вернуть штатный экран: кадр 3B 05 BB 4F 02 00."""


@dataclass(frozen=True)
class Navigate:
    """Перемещение по интерфейсу CarPlay."""

    right: bool
    steps: int


@dataclass(frozen=True)
class Select:
    """Выбор текущего пункта в CarPlay."""


@dataclass(frozen=True)
class Back:
    """Шаг назад в CarPlay."""


@dataclass(frozen=True)
class LeaveTelevision:
    """Вывести монитор из Television, оставив картинку на экране.

    Нужно, когда владелец вошёл в режим AV через меню монитора. Монитор тогда
    считает себя в Television и держит звук за собой: отбирает его заново
    каждые десять секунд, и возвращать по одному кадру бесполезно — он
    упорнее. Проверено в машине 02.10.2026.

    Поэтому не спорим, а переводим монитор в наш режим: снимаем картинку,
    возвращаем звук, показываем картинку своим кадром. После этого монитор
    в Television себя не считает и звук не трогает. Для владельца это выглядит
    как обычный вход через меню, только звук остаётся на AUX.
    """


@dataclass(frozen=True)
class PressMode:
    """Нажать за владельца кнопку MODE, чтобы перебрать источники звука.

    Прямой команды «выбрать AUX» в этой машине нет: источники ходят по кругу.
    Зато радио само пишет текущий источник на экран, и мы это видим. Значит
    можно жать и смотреть, пока не покажется AUX.
    """


@dataclass(frozen=True)
class Track:
    """Следующий или предыдущий трек."""

    forward: bool


Command = ShowPicture | HidePicture | Navigate | Select | Back | Track | PressMode | LeaveTelevision


@dataclass
class Agent:
    """Состояние и правила.

    `visible` — показываем ли мы сейчас свою картинку.
    `hidden_by_user` — убрал ли её пользователь сам. Пока это так, при
    появлении телефона картинку не навязываем: он ушёл в меню машины осознанно.
    """

    phone: bool = False
    visible: bool = False
    hidden_by_user: bool = False
    # Перебор источников до AUX. Сколько раз пробовать и как часто —
    # источников в машине немного, восьми нажатий хватает с запасом.
    want_aux: bool = False
    aux_attempts: int = 0
    last_mode_press: float = 0.0
    # Наши собственные нажатия MODE вернутся к нам с шины и будут выглядеть
    # как нажатие владельцем. Считаем их, чтобы не спутать со своими.
    pending_mode_echo: int = 0
    # Сколько раз подряд мы уже возвращали звук. Ограничение нужно, чтобы
    # не устроить перебранку с монитором, если он упрётся.
    audio_returns: int = 0
    # Сколько раз подряд мы уже возвращали себе экран. Ограничение по той же
    # причине, что и со звуком: перебранка с машиной никому не нужна.
    screen_returns: int = 0
    # После нажатия MODE уступаем экран радио: иначе владелец не увидит, какой
    # источник выбрался, а мы не прочитаем его надпись — она и есть наша
    # единственная обратная связь по звуку.
    yield_screen_to_radio: bool = False
    reclaim_after: float = 0.0
    now: float = 0.0
    speed_kmh: int = 0
    gear: str | None = None
    audio_source: str | None = None
    log: list[str] = field(default_factory=list)

    # --- входы ---------------------------------------------------------------

    def phone_connected(self, connected: bool) -> list[Command]:
        """Донгл сообщил, что телефон появился или пропал."""
        if connected == self.phone:
            return []
        self.phone = connected
        if connected:
            # Звук при подключении телефона надо перевести на нас, иначе
            # CarPlay будет виден, но не слышен. Но только если мы знаем,
            # что сейчас выбрано: пока наша картинка занимает экран, радио
            # своих надписей не шлёт, и перебор идёт вслепую. Так мы один раз
            # уже оставили источник на TV вместо AUX — 02.10.2026. Лучше не
            # трогать ничего, чем переключить наугад.
            if self.audio_source is not None and not self.our_audio:
                self.want_aux = True
                self.aux_attempts = 0
            # Если владелец сам убрал CarPlay и сидит в меню машины, телефон,
            # моргнувший Wi-Fi и вернувшийся, не должен выдёргивать его оттуда.
            # Вернуть картинку — его решение, кнопкой DISPLAY.
            if self.hidden_by_user:
                return []
            return self._show()
        # Признак «убрано вручную» здесь не сбрасываем. Иначе моргнувший Wi-Fi
        # выглядит как пропажа и возврат телефона — и картинка выпрыгивает
        # обратно, хотя владелец её убирал. Снимается он только кнопкой DISPLAY
        # или выключением зажигания, то есть новой поездкой.
        return self._hide(by_user=False)

    def on_event(self, ev: Event) -> list[Command]:
        """Событие с шины."""
        if isinstance(ev, Button):
            return self._button(ev)
        if isinstance(ev, Dial):
            # Крутилку мы сознательно отдали машине. В режиме AV видеомодуль
            # подслушивает её кадры и рисует поверх нашей картинки своё меню
            # Programme / Set / Display — секунды на две, на каждый щелчок.
            # Помешать ему нечем: он сам в шину не говорит, договариваться не с кем.
            # Проверено в машине 01.10.2026: на все остальные кнопки он не реагирует.
            return []
        if isinstance(ev, Ignition):
            if ev.state == "выключено":
                # Модуль сбросится сам, нам остаётся не врать себе о состоянии.
                self.visible = False
                self.hidden_by_user = False
            return []
        if isinstance(ev, Speed):
            self.speed_kmh = ev.kmh
            return []
        if isinstance(ev, Gear):
            self.gear = ev.name
            return []
        if isinstance(ev, RadioText):
            self.audio_source = ev.text
            if self.our_audio:
                self.want_aux = False
            return []
        if isinstance(ev, Steering):
            return self._steering(ev)
        if isinstance(ev, AudioToTv):
            if not ev.taken:
                self.audio_returns = 0
                return []
            # Звук забрали — значит вошли через меню монитора. Переводим его
            # в наш режим, но не бесконечно: если упрётся, лучше остаться без
            # звука, чем молотить по шине без конца.
            if self.phone and self.audio_returns < AUDIO_RETURN_LIMIT:
                self.audio_returns += 1
                return [LeaveTelevision()]
            return []
        if isinstance(ev, MonitorState):
            # Состояние берём у модуля, а не из своих предположений. Картинку
            # могли включить или снять мимо нас: владелец руками через меню
            # монитора, цикл зажигания, задняя передача. Если этого не делать,
            # обработчик считает CarPlay скрытым, не передаёт ему кнопки,
            # и снаружи выглядит так, будто управление забрало радио.
            was_visible = self.visible
            self.visible = ev.showing_av
            if ev.showing_av:
                self.screen_returns = 0
                self.reclaim_after = 0.0
                return []
            if self.yield_screen_to_radio and not ev.video_module_owns_screen:
                # Экран ушёл радио сразу после MODE — так и задумано.
                # Вернём картинку сами, через несколько секунд.
                self.yield_screen_to_radio = False
                self.reclaim_after = self.now + RADIO_SCREEN_SECONDS
                return []
            if not ev.video_module_owns_screen and self.phone and not self.hidden_by_user:
                # Экран ушёл машине, а мы об этом не просили. Так делает радио:
                # кнопки нижней пары адресованы ему, и, получив нажатие, оно
                # выводит свою заставку, а модуль уступает. Возвращаем картинку.
                # Проверено в машине 02.10.2026.
                if was_visible and self.screen_returns < SCREEN_RETURN_LIMIT:
                    self.screen_returns += 1
                    return [ShowPicture()]
            # Камеру заднего хода не трогаем: там экран занят модулем, просто
            # показывает не нас, и лезть туда нельзя.
            return []
        return []

    def tick(self, now: float) -> list[Command]:
        """Что сделать по времени, без внешнего события.

        Время приходит снаружи, чтобы правила оставались проверяемыми
        без ожидания в тестах.
        """
        self.now = now
        if self.reclaim_after and now >= self.reclaim_after:
            # Радио показало источник, владелец его увидел — забираем экран.
            self.reclaim_after = 0.0
            if self.phone and not self.hidden_by_user and not self.visible:
                return [ShowPicture()]
        if not (self.phone and self.want_aux):
            return []
        if self.audio_source is None:
            # Обратной связи нет — перебирать вслепую нельзя.
            self.want_aux = False
            return []
        if self.aux_attempts >= AUX_MAX_ATTEMPTS:
            self.want_aux = False
            return []
        if now - self.last_mode_press < AUX_PRESS_INTERVAL:
            return []
        self.last_mode_press = now
        self.aux_attempts += 1
        self.pending_mode_echo += 1
        return [PressMode()]

    # --- правила -------------------------------------------------------------

    def _button(self, ev: Button) -> list[Command]:
        # Удержание стрелок — это перемотка внутри трека. Принять её мы можем,
        # а сделать нечего: в протоколе донгла есть только следующий,
        # предыдущий, играть и пауза. Перемотка в CarPlay делается иначе,
        # через полосу прогресса на полном экране плеера.
        if ev.action == "удержание" or not ev.pressed:
            return []
        if ev.name == "mode":
            self.yield_screen_to_radio = True
            if self.pending_mode_echo > 0:
                # Это вернулось наше же нажатие, а не владельца.
                self.pending_mode_echo -= 1
            else:
                # Владелец выбирает источник сам — перебор прекращаем.
                self.want_aux = False
            return []
        if ev.name == "menu":
            # Уход в меню машины. Экран обязаны отпустить мы.
            return self._hide(by_user=True) if self.visible else []
        if ev.name == "display":
            if self.visible:
                return self._hide(by_user=True)
            return self._show() if self.phone else []
        # Нижняя пара стрелок монитора — перемещение по CarPlay вместо крутилки.
        # Кадры адресованы радио, и оно их тоже получит, но на источнике AUX
        # переключать ему нечего, так что вреда нет.
        if ev.name in ("vlevo", "vpravo"):
            return [Navigate(right=ev.name == "vpravo", steps=1)] if self.visible else []
        # У SELECT своя команда 0x47, поэтому её и не было в первых записях.
        if ev.name == "select":
            return [Select()] if self.visible else []
        if ev.name == "tone":
            return [Back()] if self.visible else []
        # Двойная стрелка и часы сознательно оставлены машине: чем меньше
        # штатных функций мы подменяем, тем меньше поводов удивляться.
        return []

    def _steering(self, ev: Steering) -> list[Command]:
        """Кнопки руля: переключение треков.

        Работает независимо от того, видно ли CarPlay: музыка играет и когда
        на экране меню машины. Но только если слушают именно нас — иначе
        «вперёд» на руле должна переключать станцию, а не трек в телефоне.
        """
        if not ev.pressed or not self.phone:
            return []
        if ev.name not in ("вперёд", "назад"):
            return []
        if not self.our_audio:
            return []
        return [Track(forward=ev.name == "вперёд")]

    @property
    def our_audio(self) -> bool:
        """Играет ли сейчас наш звук.

        Радио само пишет текущий источник на экран, этим и пользуемся.
        Пока оно ни разу не написало, считаем, что не наш: помешать
        переключению станции хуже, чем не переключить трек.
        """
        return bool(self.audio_source) and "AUX" in self.audio_source.upper()

    def _show(self) -> list[Command]:
        if self.visible:
            return []
        self.visible = True
        self.hidden_by_user = False
        return [ShowPicture()]

    def _hide(self, by_user: bool) -> list[Command]:
        if not self.visible:
            return []
        self.visible = False
        self.hidden_by_user = by_user
        return [HidePicture()]

# Источники по BMW I-Bus

Проверка: 30.09.2026. Для E39 / BM54 / BMBT / GT / TV. Открытая документация расшифровки сообщений не равна полной заводской спецификации; применимость зависит от блоков и прошивок.

## Основные источники

| Источник | Для чего использовать | Ограничение |
|---|---|---|
| [Wilhelm docs](https://github.com/piersholt/wilhelm-docs) | Каталог команд по блокам, поля, направления, примеры и наблюдения | Reverse engineering, есть незавершённые разделы и различия поколений |
| [BlueBus](https://github.com/tedsalmon/BlueBus) | Открытая реализация CDC, кнопок, меню и работы с шиной | Не готовый контроллер внешнего AV |
| [AVR-IBus](https://github.com/harryberlin/AVR-IBus.public) | Практическая интеграция компьютера, CDC-эмуляция, управление входом камеры | Сценарии камеры не доказывают сценарии обычного TV/AV |
| [NavCoder Readme](https://www.navcoder.com/downloads/Readme.txt) | Подключение, идентификация блоков и запись сеансов I-Bus | Нет полного открытого словаря сообщений |
| [BMW NG radio, локальная копия](sources/bmw-ng-radio-training-2000.pdf) | Заводская архитектура и распиновки раннего NG-поколения | Не каталог hex-команд, документ 06/2000 |

Дополнительные найденные указатели: [Alextronic](https://www.alextronic.de/bmw-ibus-informationen-kommunikationsbus-alter-e-reihen/), [BMWGM5 I-BUS Project](https://www.bmwgm5.com/IBUS.htm), [Geiers Wiki с ссылкой на I-Bus Inside Draft Rev.5 Франка Туанена](https://www.geier99.de/wiki/doku.php?id=ibus%3Ai-bus_bmw), [заводской ST401 Body Electronics II](https://bmwtechinfo.bmwgroup.com/tech_training_manual/ST401%20Body%20Electronics%20II.pdf). Эти страницы найдены поиском; полное содержимое в текущей проверке получить не удалось. Не приписывать им непроверенные детали.

## Что читать в Wilhelm для нашей задачи

- [rad/4e.md — Radio Source / Navigation Volume](https://github.com/piersholt/wilhelm-docs/blob/master/rad/4e.md): выбор звукового режима радио/TV и отдельные варианты для навигации.
- [vid/4f.md — Video Module Source](https://github.com/piersholt/wilhelm-docs/blob/master/vid/4f.md): управление источником видеомодуля.
- [bmbt/4f.md](https://github.com/piersholt/wilhelm-docs/blob/master/bmbt/4f.md): сообщения монитору; не смешивать с управлением видеомодулем.
- [gt/45.md](https://github.com/piersholt/wilhelm-docs/blob/master/gt/45.md) и [rad/46.md](https://github.com/piersholt/wilhelm-docs/blob/master/rad/46.md): управление интерфейсом радио и его положением относительно интерфейса GT.
- [rad/arbitration.md](https://github.com/piersholt/wilhelm-docs/blob/master/rad/arbitration.md): экспериментальные логи взаимодействия разных комбинаций GT/радио/монитора. Нельзя переносить наблюдение C23 или BM53 на BM54 без проверки.

Содержимое 4e.md, 46.md и arbitration.md прочитано через raw GitHub, поскольку веб-просмотр части страниц не работал.

### Конкретная находка: звук переключается отдельно от видео

В rad/4e.md приведены кадры GT → Radio:

```text
3B 05 68 4E 01 00 19    выбор TV-аудио
3B 05 68 4E 00 00 18    выбор режима radio
```

Это примеры из источника, не выполненные на машине команды. Здесь 3B — отправитель GT, 68 — адресат радио, 4E — команда. Последний байт — XOR предыдущих байтов.

**Важно:** второй кадр не описан как прямой выбор AUX либо CDC. Какой обычный источник восстанавливается, сохраняется ли AV-картинка и не повторяет ли GT выбор TV — ещё не установлено на нашем оборудовании.

Гипотеза для стенда: предварительно выбрать CDC/AUX, открыть TV/AV, проверить отдельный возврат звукового режима радио без смены видеорежима. Следить за 4E, 4F, 45, 46 и последующими состояниями источника. Не заменять проверку бесконечной повторной отправкой команды.

В rad/46.md также описано появление интерфейса радио поверх другого экрана с автоматическим скрытием примерно через восемь секунд в исследованных конфигурациях. Это отдельный механизм от выбора аудио.

## Что читать в BlueBus

- [firmware/application/lib/ibus.c](https://github.com/tedsalmon/BlueBus/blob/master/firmware/application/lib/ibus.c) и соседний ibus.h — реализация библиотеки шины.
- [firmware/application/handler/handler_ibus.c](https://github.com/tedsalmon/BlueBus/blob/master/firmware/application/handler/handler_ibus.c) и соседний .h — прикладные обработчики.
- [hardware](https://github.com/tedsalmon/BlueBus/tree/master/hardware) — аппаратная часть.

Пути проверены по дереву репозитория. В рамках этого поиска не проводился построчный аудит прошивки BlueBus.

## Порядок применения

1. Описание команды — Wilhelm.
2. Реализация похожего поведения — BlueBus/AVR-IBus.
3. Проверка на собственной машине — запись штатных переходов в NavCoder или нашем снифере.
4. Для каждой подтверждённой последовательности сохранять номер/HW/SW блоков, исходный режим и полный лог перехода.

Пока найдено документированное разделение команд звука, видео и интерфейса. Полный проверенный сценарий «штатный TV/AV + стерео CDC/AUX + возврат после радио» ещё не получен.

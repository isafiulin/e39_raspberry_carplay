# Выбор вычислительной платформы для компактной версии

Исследование от 04.10.2026. Источники — открытые страницы и даташиты Raspberry Pi, форумы, обзоры. Что проверено только поиском и не на железе, помечено. Решения принимать после проверки на столе (раздел 6).

## 1. Что требуется от платформы

1. Композитный видеовыход (единственный вход видеомодуля E39, см. `docs/12-variant-a-av.html`).
2. Стереозвук через I2S-кодек (WM8960 уже куплен) на линейный выход.
3. USB-хост для донгла Carlinkit CPC200-CCPA (поток H.264 800×480, звук PCM).
4. UART для I-Bus через L9637D.
5. Диапазон температур багажника и вибрация. Размер под корпус чейнджера.
6. Готовый программный стек: он написан и проверен на Raspberry Pi OS (Debian 13 trixie, Pi 4).

## 2. Главное по рынку

Среди плат формата Zero композит под Linux без доработок есть только у Raspberry Pi Zero 2 W. Платы Orange Pi, Radxa и Luckfox либо не выводят аналоговое видео вообще, либо не имеют для него драйвера в Linux. Пересматривать платформу ради «лучшего железа» нет смысла: мощность для потока 800×480 не нужна, нужны композит, звук и готовые драйверы.

| Платформа | Композит в Linux | Размер | Статус |
|---|---|---|---|
| Raspberry Pi Zero 2 W | есть, пятаки TV и GND на нижней стороне | 65×30 мм | официально $15, но [распродана почти везде](https://raspberry.tips/en/raspberrypi-infos/raspberry-pi-zero-2-w-alternative-sold-out) |
| Raspberry Pi 3A+ | есть, джек 3,5 мм | 65×56 мм | цена не менялась, наличие проверять |
| Compute Module 4 | есть (по схеме проекта `docs/02`, сверять с даташитом) | 55×40 мм + плата-носитель | варианты 2 ГБ и больше [подорожали с 02.02.2026](https://www.raspberrypi.com/news/more-memory-driven-price-rises/), 1 ГБ без изменений |
| Compute Module 3+ | есть | модуль 67,6×31 мм | не затронут подорожанием, 1 ГБ LPDDR2, [$25–40](https://www.raspberrypi.com/news/compute-module-3-on-sale-now-from-25/) |
| Orange Pi Zero 2W (H618) | **нет** в Linux, только Android; выход на плате расширения | 65×30 мм | [форум Armbian](https://forum.armbian.com/topic/46922-orangepi-zero-2w-tv-out/): драйвера нет |
| Radxa Zero 3W (RK3566) | нет данных, по чипу не ожидается | 65×30 мм | от ~$15 |
| Luckfox Lyra Zero W (RK3506B) | нет | малый | от ~$17 |
| Платы на Allwinner H3/H2+ (NanoPi M1, Orange Pi Zero) | есть, на старом ядре работает ([Armbian](https://forum.armbian.com/topic/6582-orange-pi-zero-h2h3-tv-out-on-mainline-working/)) | разный | устаревший стек |
| Ottocast, Carlinkit AI box | не найдено для E39 | — | рассчитаны на iDrive, не наш случай |

## 3. Raspberry Pi Zero 2 W: что подтверждено

- **Температура: от −20 до +70 °C** по [официальному брифу](https://datasheets.raspberrypi.com/rpizero2/raspberry-pi-zero-2-w-product-brief.pdf). Раньше в проекте звучало «0–70 °C», это было неверно. Верхняя граница 70 °C критична для багажника летом (оценка без замера: там бывает 70–85 °C), поэтому теплоотвод в стенку корпуса обязателен, а запас узкий.
- **Композит:** пятаки TV и GND на нижней стороне, рядом с mini-HDMI ([форум](https://forums.raspberrypi.com/viewtopic.php?t=381237)). Дополнительных деталей не упоминается. Конфигурация KMS: `dtoverlay=vc4-kms-v3d,composite`, `vc4.tv_norm=PAL` и в `cmdline.txt` строка `video=Composite-1:720x576@50ie,...`. Без `video=` в ряде сообщений был чёрный экран. Это те же настройки, что уже работают на Pi 4 (`docs/07`, `docs/14`).
- **Серый экран на Zero 2 W в Bookworm и Trixie** описан для рабочего стола Wayland. Причина в [открытой ошибке trixie-feedback#66](https://github.com/raspberrypi/trixie-feedback/issues/66): вывод композита не сообщает статус «подключен», и wlroots/labwc считает его отключённым. Консоль, KMS без композитора и прямое воспроизведение работают. Наш стек без Wayland, но на Zero 2 W это ещё не проверено.
- **Аппаратное декодирование H.264** (`h264_v4l2m2m`) на ядрах 6.6.63 и новее [зависает](https://github.com/raspberrypi/linux/issues/6554), открытая ошибка с 20.12.2024 (Zero 2 W, Pi 4, CM4). Обход: программный декодер. По брифу декодер железа умеет 1080p30, но рассчитывать на него в Trixie не стоит. Потянет ли программный декод 800×480@30 четыре ядра A53 на 1 ГГц с остальной нагрузкой, **не проверено**, оценка по порядку величин: нагрузка умеренная.
- Память 512 МБ.

## 4. Compute Module 4 как «правильный» вариант для надёжности

- **Температура −20…+85 °C, варианты ET (extended) до −40…+85 °C** ([бриф CM4](https://pip-assets.raspberrypi.com/categories/634-raspberry-pi-compute-module-4/documents/RP-008169-DS-8-cm4-product-brief.pdf)). Это решает температурный вопрос, который у Zero 2 W остаётся.
- **eMMC 8–64 ГБ** вместо microSD: убирает самое слабое место при вибрации.
- Декодер H.264 до 1080p60, но та же ошибка с `h264_v4l2m2m` на новых ядрах.
- Подорожание затрагивает версии с 2 ГБ и больше. **1 ГБ без изменения** (на 02.02.2026), этого достаточно. Таблица цен в брифе устаревшая, актуальные цены смотреть у реселлера.
- Нужна плата-носитель: своя (как в `docs/02`) или готовая компактная, например [Waveshare CM4 Nano Base Board](https://www.waveshare.com/cm4-nano-b.htm) размером с сам CM4. Для неё надо отдельно проверить, выведен ли композит, и подходит ли она по ножкам к WM8960.
- Минус: тот же вопрос питания, что и везде, плюс платы больше, чем у Zero.

## 5. Что отброшено и почему

- **Orange Pi Zero 2W, Radxa Zero 3W, Luckfox**: нет композита под Linux. Конвертер HDMI→AV добавил бы деталь, нагрев и непредсказуемую картинку.
- **Pico, ESP32** как основная платформа: не декодируют H.264. Годятся только как дежурный контроллер шины и питания (отдельное решение, см. `docs/18`).
- **Pi 5**: нет аппаратного декодера H.264, греется, не нужен.
- **Готовые AI-боксы**: сделаны под iDrive, для E39 с AV-входом не найдено.

## 6. Что проверить на столе, прежде чем покупать остальное

1. **Zero 2 W: композит под Trixie без рабочего стола** (Raspberry Pi OS Lite + ffplay/KMS), PAL, 720×576.
2. **Zero 2 W: загрузка процессора при программном декодировании** потока донгла 800×480@30 вместе со звуком и агентом шины, при температуре платы около 60 °C.
3. **Zero 2 W: нагрев** в закрытом ящике при нагрузке и поведение при приближении к 70 °C.

Если проверка 2 или 3 не проходит, или Zero 2 W не купить по нормальной цене, запасной путь: **CM4 1 ГБ (желательно ET) с eMMC на компактной плате-носителе**, потом Pi 3A+.

## 7. Порядок действий

1. Найти Zero 2 W у официального реселлера или подписаться на оповещение о поступлении (rpilocator).
2. Прогнать три проверки выше.
3. До покупки платы-носителя решить питание от зажигания (`docs/18`, раздел 4).
4. Если Zero 2 W не прошла: уточнить, как композит выведен на выбранной плате-носителе CM4, до заказа.

## Источники

- [Raspberry Pi Zero 2 W product brief](https://datasheets.raspberrypi.com/rpizero2/raspberry-pi-zero-2-w-product-brief.pdf)
- [Compute Module 4 product brief](https://pip-assets.raspberrypi.com/categories/634-raspberry-pi-compute-module-4/documents/RP-008169-DS-8-cm4-product-brief.pdf)
- [More memory-driven price rises (Raspberry Pi, 02.02.2026)](https://www.raspberrypi.com/news/more-memory-driven-price-rises/)
- [Prices hiked on most Raspberry Pi 4 and 5 variants (The Register, 01.04.2026)](https://www.theregister.com/on-prem/2026/04/01/prices-hiked-on-most-raspberry-pi-4-and-5-variants/5222785)
- [Composite on Pi Zero 2W — forum](https://forums.raspberrypi.com/viewtopic.php?t=381237)
- [trixie-feedback#66: composite under labwc/wlroots](https://github.com/raspberrypi/trixie-feedback/issues/66)
- [raspberrypi/linux#6554: h264_v4l2m2m на ядре 6.6.63+](https://github.com/raspberrypi/linux/issues/6554)
- [Orange Pi Zero 2W TV-OUT, Armbian forum](https://forum.armbian.com/topic/46922-orangepi-zero-2w-tv-out/)
- [Orange Pi Zero 2W review, Mehatronika](https://magazinmehatronika.com/en/orange-pi-zero-2w-review/)
- [Pi Zero 2 W sold out: alternatives 2026](https://raspberry.tips/en/raspberrypi-infos/raspberry-pi-zero-2-w-alternative-sold-out)

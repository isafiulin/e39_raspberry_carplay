# BMW E39 CarPlay Retrofit — wireless Apple CarPlay on the factory 16:9 screen

**English** · [Русский](README.ru.md)

A DIY wireless **Apple CarPlay retrofit for the BMW E39** (2002–2003, facelift) that
shows CarPlay on the **factory 16:9 widescreen navigation monitor (BMBT)** and plays
stereo sound through the **stock AUX input of the BM54 radio**. A Raspberry Pi in the
trunk talks to the car over **I-Bus**, so the original buttons and steering wheel
controls drive CarPlay. No CD changer emulation, no aftermarket head unit, no
replacement screen, no cutting the dash.

This is not a ready-made kit. It is my own wiring, my own software and a log of
everything measured on a real car. The detailed design documents are in Russian;
this page is the English summary.

## Status

**October 1, 2026: CarPlay works in the car. It shows up, you can hear it, and the stock controls work.**

- **Video** on the factory monitor through the AV input of the video module (TV module),
  filling the whole frame. Overscan margins are adjustable without code changes.
- **Audio** in stereo through the stock BM54 AUX input. Measured detection threshold:
  100 kΩ works, 220 kΩ does not. The 300 kΩ figure quoted on forums is wrong for this car.
- **Controls** use the stock buttons: arrows, SELECT, TONE, DISPLAY, MENU and the
  steering wheel buttons. The rotary knob stays with the car, because in AV mode the
  video module listens to it and draws its own menu over the picture.
- **Automation:** phone connects → CarPlay appears; phone leaves → the screen goes
  back to the car. If the audio source is taken away from the monitor menu, the
  board switches it back.
- **Reliability:** watchdog, persistent log, the service waits for the USB cable and
  survives it being unplugged. Everything starts with the ignition.
- **89 tests**, all running on I-Bus frames captured from this car.

**One open item:** picture while driving. TV-in-Motion is coded with NavCoder but
not yet confirmed on the road.

## The car

- E39, 2002–2003
- BM54 radio (in the trunk with the 16:9 monitor)
- 16:9 widescreen monitor (BMBT), 400 × 234
- Video module (TV module) with AV input
- CD-based navigation computer (GT)
- I-Bus

## How it works

```
iPhone ──Wi-Fi──► Carlinkit CPC200-CCPA ──USB (H.264 + PCM)──► Raspberry Pi
                                                                 │      │
                              composite video ◄──────────────────┘      └──► WM8960 codec
                                    │                                          │
                        Video module AV input                        BM54 radio AUX (stereo)
                                    │
                         Factory 16:9 monitor (BMBT)

                 Raspberry Pi ◄──I-Bus (KKL / TH3122)──► buttons, source switching, ignition
```

The phone connects over Wi-Fi to a **Carlinkit CPC200-CCPA** dongle. The dongle runs
a real CarPlay session (it has the Apple authentication chip) and sends **H.264
video and PCM audio over USB**. The Raspberry Pi (later a Compute Module 4 on a
custom carrier board) decodes the video, outputs **composite** into the AV input of
the video module, and sends stereo audio through a **WM8960** codec into the radio's
AUX input. The I-Bus side handles buttons, source switching and power.

The key finding, confirmed in the car on September 30, 2026: **the monitor switches
video and audio separately.** You can turn the AV picture on and off with your own
I-Bus frames (`3B 05 BB 4F 01 00` and `4F 02 00`) and the audio is not touched at
all, so it stays stereo on AUX. This removes CD changer emulation, the hardest
part of every other E39 Raspberry Pi project.

The factory CD changer harness in the trunk is reused for mounting: power, ground
and I-Bus come from its three-pin connector, identified by **wire colour**
(brown = ground, red/green = Kl.30, white/red/yellow = I-Bus), because pin
numbering differs between sources. The changer audio lines go to the CDC input,
not AUX, so AUX needs its own cable to the BM54.

### Two video options

- **[Option A](docs/12-variant-a-av.html): AV input of the video module.** Primary,
  confirmed in the car. Doesn't touch the reverse camera and needs no extra parts.
- **[Option B](docs/13-variant-b-kamera.html): reverse camera input** (white
  connector pins 13/14, selected by grounding blue connector pin 17). Fallback. Costs a
  relay to share the input with the camera.

## Repository layout

| Path | Contents |
|---|---|
| [carplay/](carplay/README.md) | Node.js CarPlay process based on node-CarPlay: talks to the dongle, shows video, plays audio, listens for commands on a local socket |
| [tools/](tools/README.md) | Python I-Bus tools: button handler with a state machine, sniffer, frame sender, device scan, log replay, bench mouse-as-finger. Tests in `tools/tests/` |
| [logs/](logs/README.md) | Real I-Bus logs captured from the car on 30.09.2026: monitor button codes, entering/leaving TV mode, ignition, gear, speed, with analysis |
| [docs/](docs/) | Design documents (Russian, open in a browser) |
| [docs/sources/](docs/sources/) | Factory BMW training PDFs for the widescreen monitor and NG radio, E38 CD changer install guide, Mura TV tuner manual |

### Key documents (Russian)

| File | Topic |
|---|---|
| [docs/01-obshchaya-shema.html](docs/01-obshchaya-shema.html) | Overall design: video and audio paths, car connectors, I-Bus addresses and messages |
| [docs/02-plata-nositel.html](docs/02-plata-nositel.html) | Carrier board spec: CM4, STM32, power, connectors, MCU↔CM4 protocol |
| [docs/03-zakupka.html](docs/03-zakupka.html) | Parts list for the bench with links and prices |
| [docs/07-pervyy-zapusk.html](docs/07-pervyy-zapusk.html) | First boot: Pi OS, dongle, audio, composite output |
| [docs/10-cheyndzher-bmw-4730en.md](docs/10-cheyndzher-bmw-4730en.md) | CD changer harness: X18180, power, I-Bus, audio harness variants |
| [docs/12-variant-a-av.html](docs/12-variant-a-av.html) | Option A, AV input: wiring, control, test procedure |
| [docs/13-ibus-istochniki.md](docs/13-ibus-istochniki.md) | I-Bus audio/video source commands |
| [docs/15-podklyuchenie-dlya-testa.html](docs/15-podklyuchenie-dlya-testa.html) | Garage cheat sheet: which OBD pins go to which wires |
| [docs/16-itogi-30-09-2026.html](docs/16-itogi-30-09-2026.html) | Day summary 30.09.2026: what the bus revealed. Start reading here |
| [docs/17-itogi-01-10-2026.html](docs/17-itogi-01-10-2026.html) | Day summary 01.10.2026: everything working in the car |
| [docs/18-kompakt-zero2w.html](docs/18-kompakt-zero2w.html) | Compact build on Raspberry Pi Zero 2 W |

Screenshots: [CarPlay on a 4.3" composite monitor](docs/images/carplay-na-monitore-4.3.jpg),
[framebuffer capture 720×576](docs/images/carplay-720x576.png).

## Roadmap

1. ~~Bench at home~~: done 29–30.09.2026. Raspberry Pi 4, dongle, composite monitor.
   CarPlay starts on boot and the UI is readable at 400 × 234.
2. ~~Sniff the bus in the car~~: done 30.09.2026. Tapped the changer connector with a KKL cable
   and captured eleven logs.
3. ~~Verify switching~~: done 30.09.2026. Picture switches with our own frame and audio isn't touched.
4. **Close two questions:** what the car's menu does over our picture, and whether
   TV-in-Motion coding removes the speed lock.
5. **Install in the car:** crimp MQS 0.63 terminals into the video module's white
   connector (pins 6 and 15), run shielded cable to the AUX input behind the monitor.
6. **Custom board:** KiCad, CM4, STM32, codec, automotive power supply, housing
   from a dead CD changer.

## Related projects

Raspberry Pi as a CD changer replacement in the E39 is well-trodden ground. None of
these projects does CarPlay, but most car-side questions were answered there.

| Project | What I took from it |
|---|---|
| [PiBUS](http://pibus.info/buy.html) | Pi board for E38/E39/E46/E53, confirms the video module pinout (blue 17, white 13/14) |
| [tedsalmon/BlueBus](https://github.com/tedsalmon/BlueBus) | Changer emulator state machine, TH3122 schematic |
| [mono.software: Hacking BMW I-BUS with Raspberry Pi](https://mono.software/2016/12/01/hacking-bmw-i-bus-with-raspberry-pi/) | Changer emulator timings |
| [bholota/IBUS-Player](https://github.com/bholota/IBUS-Player) | Protocol from the Android side |
| [rhysmorgan134/node-CarPlay](https://github.com/rhysmorgan134/node-CarPlay) | Carlinkit dongle USB protocol, the base of the CarPlay software |
| [piersholt/wilhelm-docs](https://github.com/piersholt/wilhelm-docs) | I-Bus message documentation |

What none of them have is CarPlay. They are all local media players running through
changer emulation. This project uses a dongle, the stock AUX for stereo and the
video module input for the picture, with no emulation at all.

## Keywords

BMW E39 CarPlay, E39 Apple CarPlay retrofit, E39 wireless CarPlay, BMW E39
widescreen 16:9 monitor CarPlay, BMBT CarPlay, E39 navigation CarPlay, BMW I-Bus
Raspberry Pi, E39 video module AV input, BM54 AUX, Carlinkit CPC200-CCPA,
node-CarPlay, Raspberry Pi CarPlay, E38 / E53 X5 / E46 I-Bus, CarPlay without
replacing the head unit.

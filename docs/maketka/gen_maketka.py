"""Раскладка платы питания и шины (docs/20) на макетке 31×31 отверстие.

    python3 gen_maketka.py

Пишет maketka-sverhu.svg (детали, вид со стороны деталей), maketka-snizu.svg
(провода, вид со стороны пайки, зеркально) и provoda.txt (список проводов).
Проверяет, что выводы не делят отверстия, корпуса не налезают друг на друга
и на чужие выводы, и что все выводы каждой цепи соединены.

Координаты: столбец 1–31 слева направо и ряд 1–31 сверху вниз, если смотреть
со стороны деталей. На виде снизу столбцы идут справа налево, номера те же.
"""

from __future__ import annotations

import itertools
import sys

N = 31  # отверстий по каждой стороне

# --- детали -------------------------------------------------------------------
# kind: res, dio (DO-41), tvs (DO-201), ecap (электролит), ccap (керамика),
# to92, to220, dip8, kf2 (клеммник 2 контакта), hdr (штыревой разъём)
# pins: имя вывода -> (столбец, ряд, цепь)
# body: (x1, y1, x2, y2) в шагах сетки, для проверки наложения

parts: dict[str, dict] = {}


def part(ref, kind, label, pins, body, note=""):
    parts[ref] = dict(kind=kind, label=label, pins=pins, body=body, note=note)


def vert(ref, kind, label, col, top, bottom, net_top, net_bot, half=0.5, inset=0.75, names=("1", "2"), note=""):
    """Двухвыводная деталь вертикально между рядами top и bottom."""
    part(ref, kind, label,
         {names[0]: (col, top, net_top), names[1]: (col, bottom, net_bot)},
         (col - half, top + inset, col + half, bottom - inset), note)


# Клеммники входа, слева
part("J1", "kf2", "J1 вход: +12 и масса", {"+12": (2, 3, "P12"), "GND": (2, 5, "GND")}, (0.6, 2.0, 3.6, 6.0),
     "провода от контактов 5 и 9 штекера 9-pin")
part("J2", "kf2", "J2 вход: I-Bus и масса", {"IBUS": (2, 9, "IBUS"), "GND": (2, 11, "GND")}, (0.6, 8.0, 3.6, 12.0),
     "I-Bus от контакта 4 штекера 9-pin")

# Вход и защита
vert("TVS1", "tvs", "TVS1 1.5KE27A", 6, 3, 8, "P12", "GND", half=1.1, inset=0.7, names=("K", "A"),
     note="полоса (катод) вверх, к ряду 3")
for i, row in enumerate((3, 6, 9), 1):
    part(f"C1.{i}", "ecap", f"C1.{i} 33 мкФ", {"+": (9, row, "P12"), "-": (10, row, "GND")},
         (8.3, row - 1.2, 10.7, row + 1.2), "минус (полоса) вправо")
part("C1a", "ccap", "C1a 100 нФ", {"1": (12, 3, "P12"), "2": (12, 4, "GND")}, (11.6, 2.7, 12.4, 4.3))

# Верхний ряд: резисторы и стабилитроны, выводы в рядах 3 и 7
vert("R2", "res", "R2 100k", 13, 3, 7, "P12", "Q1B")
vert("ZD1", "dio", "ZD1 1N4734A", 15, 3, 7, "Q1B", "ZR", names=("K", "A"), note="полоса (катод) вверх")
vert("R1", "res", "R1 68k", 17, 3, 7, "ZR", "IBUS")
vert("R7a", "res", "R7a 4,7k", 19, 3, 7, "P12", "R7M")
vert("R7b", "res", "R7b 4,7k", 21, 3, 7, "R7M", "QG")
vert("ZD2", "dio", "ZD2 1N4742A", 23, 3, 7, "P12", "QG", names=("K", "A"), note="полоса (катод) вверх")
vert("R8", "res", "R8 4,7k", 25, 3, 7, "QG", "NG")

# Ключ Q4 и выход на модуль 12→5 В, справа сверху
part("Q4", "to220", "Q4 IRF9540", {"G": (27, 3, "QG"), "D": (28, 3, "VKL"), "S": (29, 3, "P12")},
     (26.0, 1.9, 30.0, 3.6), "надписью вниз (к ряду 4), выводы G-D-S слева направо")
part("J3", "kf2", "J3 → модуль 5 В", {"+12В": (30, 6, "VKL"), "GND": (30, 8, "GND")},
     (28.4, 5.0, 31.4, 9.0))

# Средний ряд: детектор и Q2, выводы в рядах 10–14
part("Q1", "to92", "Q1 BC327", {"C": (13, 11, "Q1C"), "B": (14, 11, "Q1B"), "E": (15, 11, "P12")},
     (12.6, 10.2, 15.4, 11.4), "плоской стороной вниз (к ряду 12)")
vert("R3a", "res", "R3a 4,7k", 17, 10, 14, "Q1C", "R3M")
vert("R3b", "res", "R3b 4,7k", 19, 10, 14, "R3M", "NC2")
part("C2", "ecap", "C2 33 мкФ", {"+": (21, 11, "NC2"), "-": (22, 11, "GND")}, (20.3, 9.8, 22.7, 12.2),
     "минус (полоса) вправо")
vert("R4", "res", "R4 680k", 24, 10, 14, "NC2", "GND")
part("Q2", "to220", "Q2 IRF530N", {"G": (26, 12, "NC2"), "D": (27, 12, "NG"), "S": (28, 12, "GND")},
     (25.0, 10.9, 29.0, 12.6), "надписью вниз (к ряду 13), выводы G-D-S слева направо")

# Нижний ряд: трансивер, HOLD, Q3
part("U1", "dip8", "U1 L9637D на переходнике",
     {"1 RX": (13, 17, "RX"), "2 LO": (13, 18, "NC"), "3 VCC": (13, 19, "V33"), "4 TX": (13, 20, "TX"),
      "5 GND": (16, 20, "GND"), "6 K": (16, 19, "IBUS"), "7 VS": (16, 18, "VS"), "8 LI": (16, 17, "GND")},
     (12.5, 16.4, 16.5, 20.6), "ключ (вывод 1) слева сверху. Если ряды переходника на 0,6″, правый ряд — столбец 19")
part("Cvs", "ccap", "100 нФ", {"1": (16, 15, "VS"), "2": (17, 15, "GND")}, (15.7, 14.6, 17.3, 15.4))
part("Cvcc", "ccap", "100 нФ", {"1": (11, 19, "V33"), "2": (11, 20, "GND")}, (10.6, 18.7, 11.4, 20.3))
vert("R12", "res", "R12 4,7k", 18, 17, 21, "V33", "TX")
vert("D3", "dio", "D3 1N4007", 20, 17, 21, "VKL", "VS", names=("A", "K"), note="полоса (катод) вниз, к ряду 21")
vert("R6", "res", "R6 100k", 22, 17, 21, "Q3B", "GND")
part("Q3", "to92", "Q3 BC337-40", {"C": (24, 19, "NG"), "B": (25, 19, "Q3B"), "E": (26, 19, "GND")},
     (23.6, 18.2, 26.4, 19.4), "плоской стороной вниз (к ряду 20)")
vert("R5a", "res", "R5a 4,7k", 28, 16, 20, "HOLD", "R5M")
vert("R5b", "res", "R5b 4,7k", 30, 16, 20, "R5M", "Q3B")

# Разъём к малине
part("J4", "hdr", "J4 к малине", {"3V3": (13, 26, "V33"), "GND": (14, 26, "GND"), "TX": (15, 26, "TX"),
                                  "RX": (16, 26, "RX"), "HOLD": (17, 26, "HOLD")},
     (12.5, 25.5, 17.5, 26.5), "пины малины: 1, 6, 8, 10, 37")

NET_NAMES = {
    "P12": "+12_ЗАЩ", "GND": "масса", "IBUS": "I-Bus", "Q1B": "база Q1", "ZR": "ZD1–R1", "Q1C": "коллектор Q1",
    "R3M": "середина R3", "NC2": "узел C2", "NG": "узел G", "QG": "затвор Q4", "R7M": "середина R7",
    "VKL": "+12_ВКЛ", "VS": "VS трансивера", "HOLD": "HOLD", "R5M": "середина R5", "Q3B": "база Q3",
    "V33": "+3,3 В", "TX": "TX", "RX": "RX",
}
NET_COLORS = {
    "P12": "#d62828", "GND": "#111111", "IBUS": "#1f6feb", "VKL": "#f08c00", "VS": "#b8860b", "V33": "#0e9a9a",
    "TX": "#6f42c1", "RX": "#a23cc8", "HOLD": "#2f9e44", "Q1B": "#e64980", "ZR": "#9c6644", "Q1C": "#5c940d",
    "R3M": "#748ffc", "NC2": "#c2255c", "NG": "#495057", "QG": "#e8590c", "R7M": "#94d82d", "R5M": "#66a80f",
    "Q3B": "#ae3ec9",
}
OTHER = "#7a3fb0"


def cname(c):
    return f"ст.{c}"


def hole(c, r):
    return f"{c}/{r}"


# --- проверки -------------------------------------------------------------------
errors = []
used = {}
for ref, p in parts.items():
    for name, (c, r, net) in p["pins"].items():
        if not (1 <= c <= N and 1 <= r <= N):
            errors.append(f"{ref}.{name} вне платы: {c}/{r}")
        if (c, r) in used:
            errors.append(f"отверстие {c}/{r} занято дважды: {used[(c, r)]} и {ref}.{name}")
        used[(c, r)] = f"{ref}.{name}"


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


for (ra, pa), (rb, pb) in itertools.combinations(parts.items(), 2):
    if overlap(pa["body"], pb["body"]):
        errors.append(f"корпуса налезают: {ra} и {rb}")
for ref, p in parts.items():
    x1, y1, x2, y2 = p["body"]
    for (c, r), who in used.items():
        if who.split(".")[0] == ref or who.startswith(ref + "."):
            continue
        if x1 < c < x2 and y1 < r < y2:
            errors.append(f"корпус {ref} закрывает вывод {who} ({c}/{r})")

nets: dict[str, list] = {}
for ref, p in parts.items():
    for name, (c, r, net) in p["pins"].items():
        if net == "NC":
            continue
        nets.setdefault(net, []).append((c, r, f"{ref}.{name}"))
for net, pins in nets.items():
    if len(pins) < 2:
        errors.append(f"цепь {net} из одного вывода: {pins}")

if errors:
    print("ОШИБКИ:\n" + "\n".join(errors))
    sys.exit(1)


# --- провода: минимальное остовное дерево по каждой цепи ------------------------
def mst(pins):
    done = [pins[0]]
    rest = pins[1:]
    edges = []
    while rest:
        best = min(((a, b) for a in done for b in rest), key=lambda e: abs(e[0][0] - e[1][0]) + abs(e[0][1] - e[1][1]))
        edges.append(best)
        done.append(best[1])
        rest.remove(best[1])
    return edges


wires = {net: mst(pins) for net, pins in nets.items()}

ORDER = ["P12", "GND", "IBUS", "Q1B", "ZR", "Q1C", "R3M", "NC2", "NG", "QG", "R7M", "VKL", "VS", "HOLD", "R5M",
         "Q3B", "V33", "TX", "RX"]
lines = ["Провода снизу платы. Координаты: столбец/ряд, как на виде сверху.", ""]
total = 0
for net in ORDER:
    lines.append(f"{NET_NAMES[net]} ({net}):")
    for a, b in wires[net]:
        total += 1
        lines.append(f"  {total:2d}. {a[2]:<10} {hole(a[0], a[1]):>6}  →  {b[2]:<10} {hole(b[0], b[1]):>6}")
    lines.append("")
lines.append(f"Всего проводов: {total}")
open("provoda.txt", "w").write("\n".join(lines) + "\n")

# --- рисование ----------------------------------------------------------------
S = 22          # шаг сетки в пикселях
M = 40          # поле
W = M * 2 + S * (N - 1)


def X(c, mirror):
    return M + S * ((N - c) if mirror else (c - 1))


def Y(r):
    return M + S * (r - 1)


def svg(mirror):
    o = [f'<svg viewBox="0 0 {W} {W + 30}" xmlns="http://www.w3.org/2000/svg" font-family="IBM Plex Sans, Arial, sans-serif">',
         f'<rect x="8" y="8" width="{W - 16}" height="{W - 16}" rx="10" fill="#f4f1e8" stroke="#b9b29f"/>']
    for c in range(1, N + 1):
        for r in range(1, N + 1):
            o.append(f'<circle cx="{X(c, mirror)}" cy="{Y(r)}" r="4.2" fill="#ffffff" stroke="#c8bfa4"/>')
    for c in range(1, N + 1, 2):
        o.append(f'<text x="{X(c, mirror)}" y="24" font-size="10" text-anchor="middle" fill="#8a826c">{c}</text>')
    for r in range(1, N + 1, 2):
        o.append(f'<text x="22" y="{Y(r) + 3}" font-size="10" text-anchor="middle" fill="#8a826c">{r}</text>')
    if mirror:
        allpins = [(c, r) for p in parts.values() for (c, r, _) in p["pins"].values()]
        num = 0
        labels = []
        for net in ORDER:
            col = NET_COLORS.get(net, OTHER)
            for a, b in wires[net]:
                num += 1
                (ax, ay), (bx, by) = (a[0], a[1]), (b[0], b[1])
                dx, dy = bx - ax, by - ay
                L = (dx * dx + dy * dy) ** 0.5
                # проходит ли прямая над чужим выводом
                bow = 0.0
                for (pc, pr) in allpins:
                    if (pc, pr) in ((ax, ay), (bx, by)):
                        continue
                    t = ((pc - ax) * dx + (pr - ay) * dy) / (L * L)
                    if 0 < t < 1:
                        d = abs((pc - ax) * dy - (pr - ay) * dx) / L
                        if d < 0.45:
                            bow = 0.9 if bow == 0 else bow
                nx, ny = -dy / L, dx / L
                mx, my = (ax + bx) / 2 + nx * bow, (ay + by) / 2 + ny * bow
                x1, y1, x2, y2 = X(ax, True), Y(ay), X(bx, True), Y(by)
                qx, qy = X(mx, True), Y(my)
                cx, cy = 2 * qx - (x1 + x2) / 2, 2 * qy - (y1 + y2) / 2
                o.append(f'<path d="M{x1},{y1} Q{cx},{cy} {x2},{y2}" '
                         f'fill="none" stroke="{col}" stroke-width="3.2" stroke-linecap="round" opacity=".9"/>')
                # номер ставим в свободное место на кривой
                pinpx = [(X(c, True), Y(r)) for c, r in allpins]
                best = None
                for t in (0.5, 0.4, 0.6, 0.3, 0.7, 0.22, 0.78):
                    px = (1 - t) ** 2 * x1 + 2 * t * (1 - t) * cx + t * t * x2
                    py = (1 - t) ** 2 * y1 + 2 * t * (1 - t) * cy + t * t * y2
                    near = min([((px - lx) ** 2 + (py - ly) ** 2) ** 0.5 for lx, ly, _, _ in labels] +
                               [((px - lx) ** 2 + (py - ly) ** 2) ** 0.5 + 6 for lx, ly in pinpx] + [99])
                    if best is None or near > best[0]:
                        best = (near, px, py)
                    if near >= 19:
                        break
                labels.append((best[1], best[2], num, col))
        for qx, qy, n, col in labels:
            o.append(f'<circle cx="{qx}" cy="{qy}" r="8" fill="#fff" stroke="{col}" stroke-width="1.5"/>'
                     f'<text x="{qx}" y="{qy + 3.5}" font-size="9.5" text-anchor="middle" fill="#16191d" font-weight="700">{n}</text>')
        for ref, p in parts.items():
            for name, (c, r, net) in p["pins"].items():
                col = NET_COLORS.get(net, OTHER) if net != "NC" else "#aaa"
                o.append(f'<circle cx="{X(c, True)}" cy="{Y(r)}" r="6" fill="{col}"/>')
        o.append(f'<text x="{W / 2}" y="{W + 18}" font-size="14" text-anchor="middle" fill="#16191d">'
                 f'Вид СНИЗУ, со стороны пайки (зеркально). Провода в изоляции.</text>')
    else:
        for ref, p in parts.items():
            x1, y1, x2, y2 = p["body"]
            bx1, bx2 = sorted((X(x1, False), X(x2, False)))
            k = p["kind"]
            fill = {"res": "#e8d6a8", "dio": "#3a3a3a", "tvs": "#2d2d2d", "ecap": "#2f5d9a", "ccap": "#d9a441",
                    "to92": "#222", "to220": "#222", "dip8": "#1f5f3f", "kf2": "#2a7f62", "hdr": "#222"}[k]
            if k == "ecap":
                cx, cy, rr = (bx1 + bx2) / 2, (Y(y1) + Y(y2)) / 2, (bx2 - bx1) / 2
                o.append(f'<circle cx="{cx}" cy="{cy}" r="{rr}" fill="{fill}" opacity=".85"/>')
            else:
                o.append(f'<rect x="{bx1}" y="{Y(y1)}" width="{bx2 - bx1}" height="{Y(y2) - Y(y1)}" rx="3" '
                         f'fill="{fill}" opacity=".85"/>')
            for name, (c, r, net) in p["pins"].items():
                o.append(f'<circle cx="{X(c, False)}" cy="{Y(r)}" r="5" fill="#c9a227" stroke="#16191d" stroke-width="1"/>')
                short = name.split()[0] if k == "dip8" else name
                if k == "dip8":
                    dx = 13 if c == min(pc for pc, _, _ in p["pins"].values()) else -13
                    o.append(f'<text x="{X(c, False) + dx}" y="{Y(r) + 4}" font-size="10" text-anchor="middle" fill="#fff" font-weight="700">{short}</text>')
                if k in ("to92", "to220", "kf2", "hdr", "dio", "tvs", "ecap"):
                    o.append(f'<text x="{X(c, False)}" y="{Y(r) + (16 if k in ("to92", "to220", "hdr") else -8)}" '
                             f'font-size="9" text-anchor="middle" fill="#16191d" font-weight="600">{short}</text>')
            # подпись
            lx = (bx1 + bx2) / 2
            ly = Y(y1) - 5 if k not in ("res", "dio", "tvs") else (Y(y1) + Y(y2)) / 2
            if k in ("res", "dio", "tvs"):
                o.append(f'<text x="{bx2 + 3}" y="{ly}" font-size="10" fill="#16191d" font-weight="600" '
                         f'transform="rotate(-90 {bx2 + 3} {ly})" text-anchor="middle" dy="8">{p["label"]}</text>')
            else:
                o.append(f'<text x="{lx}" y="{ly}" font-size="10" text-anchor="middle" fill="#16191d" '
                         f'font-weight="600">{p["label"]}</text>')
            if k in ("dio", "tvs"):
                kc, kr, _ = p["pins"]["K"]
                ar = p["pins"]["A"][1]
                by = Y(y1) + 4 if kr < ar else Y(y2) - 7
                o.append(f'<rect x="{bx1}" y="{by}" width="{bx2 - bx1}" height="3" fill="#e8e8e8"/>')
        o.append(f'<text x="{W / 2}" y="{W + 18}" font-size="14" text-anchor="middle" fill="#16191d">'
                 f'Вид СВЕРХУ, со стороны деталей</text>')
    o.append("</svg>")
    return "\n".join(o)


open("maketka-sverhu.svg", "w").write(svg(False))
open("maketka-snizu.svg", "w").write(svg(True))
print(f"проверки пройдены: {len(parts)} деталей, {sum(len(p['pins']) for p in parts.values())} выводов, "
      f"{len(nets)} цепей, {total} проводов")

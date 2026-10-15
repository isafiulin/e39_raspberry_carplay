"""Модель платы питания и шины для Falstad CircuitJS (docs/20-plata-pitaniya-i-shiny.html).

    python3 gen_plata.py ТРАФИК НАПРЯЖЕНИЕ_C2 ШАГ ИМЯ
    python3 gen_plata.py 1 0 0.001 20-plata-pitaniya   # трафик включён, C2 пустой

Пишет ИМЯ.txt (вставить в Falstad через File → Import From Text) и ИМЯ.url.
"""
import urllib.parse, sys
TRAFFIC = sys.argv[1] == "1"
C2V = float(sys.argv[2])
DT = sys.argv[3]
OUT = sys.argv[4]

els = []     # (строка, [посты])
wires = []   # отрезки

def E(line, *posts):
    els.append((line, list(posts)))

def W(*pts):
    for a, b in zip(pts, pts[1:]):
        wires.append((a, b))

def R(x1, y1, x2, y2, ohm): E(f"r {x1} {y1} {x2} {y2} 0 {ohm}", (x1, y1), (x2, y2))
def C(x1, y1, x2, y2, f): E(f"c {x1} {y1} {x2} {y2} 0 {f} 0", (x1, y1), (x2, y2))
def G(x, y): E(f"g {x} {y} {x} {y+16} 0 0", (x, y))
def Z(xa, ya, xk, yk, v): E(f"z {xa} {ya} {xk} {yk} 1 0.805904783 {v}", (xa, ya), (xk, yk))
def D(xa, ya, xk, yk): E(f"d {xa} {ya} {xk} {yk} 2 default", (xa, ya), (xk, yk))
def RAIL(x, y, v): E(f"R {x} {y} {x} {y-16} 0 0 40 {v} 0 0 0.5", (x, y))
def LBL(x, y, name): E(f"207 {x} {y} {x+32} {y} 4 {name}", (x, y))
def NPN(bx, by, beta=200):  # база (bx,by), коллектор сверху, эмиттер снизу
    E(f"t {bx} {by} {bx+48} {by} 0 1 0 0 {beta}", (bx, by), (bx+48, by-16), (bx+48, by+16))
def PNP(bx, by, beta=200):  # эмиттер сверху, коллектор снизу
    E(f"t {bx} {by} {bx+48} {by} 0 -1 0 0 {beta}", (bx, by), (bx+48, by+16), (bx+48, by-16))
def NMOS(gx, gy, vt, beta):  # сток сверху, исток снизу
    E(f"f {gx} {gy} {gx+48} {gy} 0 {vt} {beta}", (gx, gy), (gx+48, gy-16), (gx+48, gy+16))
def PMOS(gx, gy, vt, beta):  # исток сверху, сток снизу (проверяется симуляцией)
    E(f"f {gx} {gy} {gx+48} {gy} 1 {vt} {beta}", (gx, gy), (gx+48, gy-16), (gx+48, gy+16))
def SW(x1, y1, x2, y2, closed): E(f"s {x1} {y1} {x2} {y2} 0 {0 if closed else 1} false", (x1, y1), (x2, y2))

# --- Kl.30 и вход ---
RAIL(0, 48, 12.6)
W((0, 48), (720, 48))
Z(64, 160, 64, 48, 27); G(64, 160)                 # TVS1 1.5KE27A
C(112, 48, 112, 160, 0.0001); G(112, 160)          # C1 = 3 × 33 мкФ
LBL(0, 48, "Kl30")

# --- модель шины: подтяжка блоков + «блок, который передаёт» ---
R(160, 48, 160, 208, 1000)
NMOS(112, 256, 2, 0.5); G(160, 272)                # передатчик (ключ на землю)
W((160, 208), (160, 240))
E("R 16 336 16 320 0 2 100 2.5 2.5 0 0.3", (16, 336))  # кадры: меандр 100 Гц, доминанта 30 %
SW(16, 336, 64, 336, TRAFFIC)                         # выключатель «трафик на шине»
W((64, 336), (112, 336), (112, 256))
R(112, 336, 112, 416, 100000); G(112, 416)
LBL(160, 208, "IBus")

# --- детектор ---
R(256, 48, 256, 112, 100000)                       # R2
PNP(256, 112)                                      # Q1 BC327: эмиттер (304,96), коллектор (304,128)
W((304, 96), (304, 48))
Z(256, 176, 256, 112, 5.6)                         # ZD1
R(256, 176, 256, 208, 68000)                       # R1
W((160, 208), (256, 208))
R(304, 128, 304, 240, 9400)                        # R3 = 2 × 4,7k, без D2
W((304, 240), (448, 240))
E(f"c 352 240 352 304 0 0.000033 {C2V}", (352, 240), (352, 304)); G(352, 304)  # C2 33 мкФ        # C2
R(400, 240, 400, 304, 680000); G(400, 304)         # R4
LBL(352, 240, "C2")

# --- ключ ---
NMOS(448, 240, 3, 1)                               # Q2 IRF530N: сток (496,224), исток (496,256)
G(496, 256)
W((496, 224), (496, 176), (672, 176))
NPN(560, 240)                                      # Q3 BC337-40: коллектор (608,224), эмиттер (608,256)
W((608, 224), (608, 176)); G(608, 256)
R(672, 48, 672, 112, 9400)                         # R7 = 2 × 4,7k
Z(640, 112, 640, 48, 15)                           # ZD2
W((640, 112), (672, 112))
R(672, 112, 672, 176, 4700)                        # R8
PMOS(672, 112, 3, 1)                               # Q4 IRF9540: исток (720,96), сток (720,128)
W((720, 96), (720, 48))
W((720, 128), (800, 128))
R(800, 128, 800, 208, 15); G(800, 208)             # малина + донгл через преобразователь ≈ 0,8 А
LBL(800, 128, "VKL")
LBL(672, 176, "G")

# --- HOLD от малины ---
RAIL(960, 336, 3.3)
SW(912, 336, 960, 336, False)                      # выключатель «HOLD»
W((912, 336), (528, 336))
R(528, 336, 528, 288, 9400)                        # R5 = 2 × 4,7k
W((528, 288), (528, 240), (560, 240))
R(544, 240, 544, 304, 100000); G(544, 304)         # R6
LBL(912, 336, "HOLD")


# --- разбить провода в точках подключения ---
posts = {p for _, ps in els for p in ps} | {p for w in wires for p in w}
out_w = []
for (a, b) in wires:
    (x1, y1), (x2, y2) = a, b
    pts = [p for p in posts if p not in (a, b) and
           ((x1 == x2 == p[0] and min(y1, y2) < p[1] < max(y1, y2)) or
            (y1 == y2 == p[1] and min(x1, x2) < p[0] < max(x1, x2)))]
    pts.sort(key=lambda p: abs(p[0]-x1) + abs(p[1]-y1))
    seq = [a] + pts + [b]
    for p, q in zip(seq, seq[1:]):
        out_w.append(f"w {p[0]} {p[1]} {q[0]} {q[1]} 0")

text = f"$ 1 {DT} 10.2 50 15 50 5e-11\n" + "\n".join(l for l, _ in els) + "\n" + "\n".join(out_w) + "\n"
open(OUT + ".txt", "w").write(text)
open(OUT + ".url", "w").write("https://www.falstad.com/circuit/circuitjs.html?cct=" + urllib.parse.quote(text))
print(len(text))

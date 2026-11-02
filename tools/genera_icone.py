"""Genera le icone dell'applicazione, senza librerie esterne.

Servono al telefono per installare la pagina come app (manifest.webmanifest).
Disegna un quadrato arrotondato scuro con una linea di prezzo chiara, e scrive
due PNG: 192 e 512 pixel.

    python tools/genera_icone.py
"""

from __future__ import annotations

import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")

SFONDO = (26, 26, 25)        # la superficie scura della dashboard
LINEA = (57, 135, 229)       # il blu della serie 1
PUNTO = (12, 163, 12)        # il verde "da guardare adesso"

# andamento stilizzato: valori 0..1 da sinistra a destra
SERIE = [0.18, 0.22, 0.20, 0.30, 0.34, 0.31, 0.44, 0.50, 0.47, 0.62, 0.72, 0.80]


def png(width: int, height: int, pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    raw = bytearray()
    for row in pixels:
        raw.append(0)                      # filtro "none"
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)   # RGBA
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", comp) + chunk(b"IEND", b""))


def disegna(size: int) -> list[list[tuple[int, int, int, int]]]:
    px = [[(0, 0, 0, 0) for _ in range(size)] for _ in range(size)]
    raggio = int(size * 0.22)

    def dentro(x: int, y: int) -> bool:
        """Quadrato con gli angoli arrotondati."""
        for cx, cy in ((raggio, raggio), (size - 1 - raggio, raggio),
                       (raggio, size - 1 - raggio), (size - 1 - raggio, size - 1 - raggio)):
            if (x < raggio and y < raggio) or (x > size - 1 - raggio and y < raggio) or \
               (x < raggio and y > size - 1 - raggio) or \
               (x > size - 1 - raggio and y > size - 1 - raggio):
                if (x - cx) ** 2 + (y - cy) ** 2 <= raggio ** 2:
                    return True
                continue
        if raggio <= x <= size - 1 - raggio or raggio <= y <= size - 1 - raggio:
            return True
        return False

    for y in range(size):
        for x in range(size):
            if dentro(x, y):
                px[y][x] = (*SFONDO, 255)

    # la linea: dai punti della serie, con spessore proporzionale
    margine = int(size * 0.22)
    largh = size - 2 * margine
    alt = size - 2 * margine
    spessore = max(4, int(size * 0.09))
    punti = []
    for i, v in enumerate(SERIE):
        x = margine + round(largh * i / (len(SERIE) - 1))
        y = size - margine - round(alt * v)
        punti.append((x, y))

    def pennello(cx: int, cy: int, colore, raggio_p: int) -> None:
        for dy in range(-raggio_p, raggio_p + 1):
            for dx in range(-raggio_p, raggio_p + 1):
                if dx * dx + dy * dy <= raggio_p * raggio_p:
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size and px[y][x][3]:
                        px[y][x] = (*colore, 255)

    for (x0, y0), (x1, y1) in zip(punti, punti[1:]):
        passi = max(abs(x1 - x0), abs(y1 - y0), 1)
        for s in range(passi + 1):
            pennello(round(x0 + (x1 - x0) * s / passi),
                     round(y0 + (y1 - y0) * s / passi), LINEA, spessore // 2)

    # il punto finale, come l'ultimo prezzo nei grafici
    pennello(*punti[-1], PUNTO, max(3, int(size * 0.075)))
    return px


def main() -> int:
    for size in (192, 512):
        data = png(size, size, disegna(size))
        path = os.path.join(WEB, f"icona-{size}.png")
        with open(path, "wb") as fh:
            fh.write(data)
        print(f"scritto {os.path.relpath(path, ROOT)} ({len(data) / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Generates the PWA icons (pure stdlib, no Pillow). Run: python scripts/make_icons.py"""
import math
import struct
import zlib
from pathlib import Path

NAVY = (18, 36, 58)
ORANGE = (255, 106, 19)
WHITE = (255, 255, 255)
OUT = Path(__file__).resolve().parent.parent / "app" / "static" / "icons"


def png(path, size, pixel):
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            row += bytes(pixel(x, y, size))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(data)


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def design(scale):
    """Orange circle with a white handset-style tick of 'sound waves'."""
    def shade(px, py):
        # px, py in [-1, 1]. Circle centred; waves start left of centre.
        if math.hypot(px, py) / scale >= 0.62:
            return NAVY
        color = ORANGE
        wx = px + 0.2 * scale
        r = math.hypot(wx, py) / scale
        ang = math.atan2(py, wx)
        if -0.85 < ang < 0.85:
            for radius in (0.18, 0.33, 0.48):
                if abs(r - radius) < 0.045:
                    color = WHITE
        if r < 0.075:
            color = WHITE
        return color

    def pixel(x, y, size):
        acc = [0, 0, 0]
        n = 3
        for sy in range(n):
            for sx in range(n):
                px = ((x + (sx + .5) / n) / size) * 2 - 1
                py = ((y + (sy + .5) / n) / size) * 2 - 1
                c = shade(px, py)
                for i in range(3):
                    acc[i] += c[i]
        return tuple(round(v / (n * n)) for v in acc)

    return pixel


OUT.mkdir(parents=True, exist_ok=True)
png(OUT / "icon-192.png", 192, design(1.25))
png(OUT / "icon-512.png", 512, design(1.25))
png(OUT / "icon-512-maskable.png", 512, design(1.0))
png(OUT / "apple-touch-icon.png", 180, design(1.25))
print("icons written to", OUT)

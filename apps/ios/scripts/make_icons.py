#!/usr/bin/env python3
"""Renders the app icon and the launch image from the same shapes as Android's
launcher icon (res/drawable/ic_launcher_foreground.xml: the white chat bubble
with three moss dots, on moss #589B31):

  NeemaApp/Assets.xcassets/AppIcon.appiconset/icon-1024.png   opaque 1024 × 1024
  NeemaApp/Assets.xcassets/LaunchIcon.imageset/launch@2x.png  240 × 240, a rounded square on transparency
  NeemaApp/Assets.xcassets/LaunchIcon.imageset/launch@3x.png  360 × 360

Pure Python (zlib + struct) so it runs on any box: `python3 apps/ios/scripts/make_icons.py`.
"""
import os
import struct
import sys
import zlib

MOSS = (0x58, 0x9B, 0x31)
WHITE = (255, 255, 255)
HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "NeemaApp", "Assets.xcassets")


def in_triangle(px, py, a, b, c):
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = sign((px, py), a, b), sign((px, py), b, c), sign((px, py), c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def bubble(x, y):
    """The bubble in its 48-unit box: an ellipse centred (24, 21), radii (20, 17), with the tail toward (7, 43)."""
    if ((x - 24) / 20) ** 2 + ((y - 21) / 17) ** 2 <= 1:
        return True
    return in_triangle(x, y, (9.34, 32.55), (7, 43), (18.2, 37.4))


def dot(x, y):
    return any((x - cx) ** 2 + (y - 21) ** 2 <= 2.5 ** 2 for cx in (15, 24, 33))


def in_rounded_square(x, y, size, r):
    if x < 0 or y < 0 or x > size or y > size:
        return False
    cx = r if x < r else (size - r if x > size - r else x)
    cy = r if y < r else (size - r if y > size - r else y)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def render(size, bubble_fraction, corner_fraction=None, samples=3):
    """Rows of RGB (opaque) or RGBA (rounded, transparent corners) pixels."""
    opaque = corner_fraction is None
    scale = size * bubble_fraction / 48.0
    offset = (size - 48 * scale) / 2
    radius = None if opaque else size * corner_fraction
    n = samples * samples
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = 0
            covered = 0
            for sy in range(samples):
                for sx in range(samples):
                    x = px + (sx + 0.5) / samples
                    y = py + (sy + 0.5) / samples
                    if radius is not None and not in_rounded_square(x, y, size, radius):
                        continue
                    bx, by = (x - offset) / scale, (y - offset) / scale
                    col = WHITE if bubble(bx, by) and not dot(bx, by) else MOSS
                    r += col[0]; g += col[1]; b += col[2]
                    covered += 1
            if opaque:
                row += bytes((round(r / n), round(g / n), round(b / n)))
            elif covered == 0:
                row += bytes((0, 0, 0, 0))
            else:
                row += bytes((round(r / covered), round(g / covered), round(b / covered), round(255 * covered / n)))
        rows.append(bytes(row))
    return rows, opaque


def png(size, rows, opaque):
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 2 if opaque else 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    print(f"wrote {os.path.relpath(path, HERE)} ({len(data)} bytes)")


def main():
    # The app icon: iOS masks the corners itself, so a full moss square with the bubble at 56% (Android's 48 of 66 safe dp).
    rows, opaque = render(1024, 0.56, samples=3)
    write(os.path.join(ASSETS, "AppIcon.appiconset", "icon-1024.png"), png(1024, rows, opaque))
    # The launch image: the splash's moss tile (a 22% rounded square) on the night background set in the asset catalog.
    for scale in (2, 3):
        size = 120 * scale
        rows, opaque = render(size, 0.56, corner_fraction=0.22, samples=4)
        write(os.path.join(ASSETS, "LaunchIcon.imageset", f"launch@{scale}x.png"), png(size, rows, opaque))


if __name__ == "__main__":
    sys.exit(main())

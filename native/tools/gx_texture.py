#!/usr/bin/env python3
"""Decode GX textures (J3D TEX1 entries, .bti files) to RGBA, and write PNG.

Formats (GX_TF_*): I4, I8, IA4, IA8, RGB565, RGB5A3, RGBA8, C4, C8, C14X2 (palette IA8, RGB565 or
RGB5A3) and CMPR (DXT1-like 4x4 blocks, four to an 8x8 tile). Pixels are stored in tiles (I4 and C4
8x8, I8/IA4/C8 8x4, the 16-bit formats 4x4, RGBA8 4x4 in two 32-byte halves AR then GB), tiles row
by row; the image is padded to whole tiles. All decoding is numpy.

    decode_tex1(header: bytes, image: bytes, palette: bytes | None) -> uint8 (h, w, 4)
    texture_entries(tex1_block) -> [(name, header, image bytes, palette bytes)]
    write_png(path, rgba)

    gx_texture.py dump MODEL_OR_ARC OUT_DIR    every texture of a model as PNG
"""
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

TILE = {0: (8, 8), 1: (8, 4), 2: (8, 4), 3: (4, 4), 4: (4, 4), 5: (4, 4), 6: (4, 4), 8: (8, 8), 9: (8, 4), 10: (4, 4), 14: (8, 8)}
BITS = {0: 4, 1: 8, 2: 8, 3: 16, 4: 16, 5: 16, 6: 32, 8: 4, 9: 8, 10: 16, 14: 4}


def _untile(values: np.ndarray, w: int, h: int, tw: int, th: int) -> np.ndarray:
    """values: per pixel in tile order (any trailing dims) -> (h, w, ...)."""
    bw, bh = (w + tw - 1) // tw, (h + th - 1) // th
    tail = values.shape[1:]
    grid = values[:bw * bh * tw * th].reshape((bh, bw, th, tw) + tail)
    image = grid.swapaxes(1, 2).reshape((bh * th, bw * tw) + tail)
    return image[:h, :w]


def _expand(v, bits):
    return ((v.astype(np.uint32) * 255 + ((1 << bits) - 1) // 2) // ((1 << bits) - 1)).astype(np.uint8)


def _rgb565(v):
    v = v.astype(np.uint32)
    return np.stack([_expand(v >> 11 & 31, 5), _expand(v >> 5 & 63, 6), _expand(v & 31, 5), np.full(v.shape, 255, np.uint8)], -1)


def _rgb5a3(v):
    v = v.astype(np.uint32)
    opaque = (v & 0x8000) != 0
    rgb555 = np.stack([_expand(v >> 10 & 31, 5), _expand(v >> 5 & 31, 5), _expand(v & 31, 5), np.full(v.shape, 255, np.uint8)], -1)
    argb3444 = np.stack([_expand(v >> 8 & 15, 4), _expand(v >> 4 & 15, 4), _expand(v & 15, 4), _expand(v >> 12 & 7, 3)], -1)
    return np.where(opaque[..., None], rgb555, argb3444)


def _ia8(v):
    v = v.astype(np.uint32)
    i, a = (v & 0xFF).astype(np.uint8), (v >> 8).astype(np.uint8)
    return np.stack([i, i, i, a], -1)


def _palette(data: bytes, fmt: int, count: int):
    v = np.frombuffer(data[:count * 2], ">u2")
    return {0: _ia8, 1: _rgb565, 2: _rgb5a3}[fmt](v)


def _nibbles(data):
    b = np.frombuffer(data, np.uint8)
    return np.stack([b >> 4, b & 15], -1).reshape(-1)


def _cmpr(data: bytes, w: int, h: int) -> np.ndarray:
    blocks = np.frombuffer(data, np.uint8)
    count = len(blocks) // 8
    blocks = blocks[:count * 8].reshape(count, 8)
    c0 = blocks[:, 0].astype(np.uint32) << 8 | blocks[:, 1]
    c1 = blocks[:, 2].astype(np.uint32) << 8 | blocks[:, 3]
    p0, p1 = _rgb565(c0).astype(np.int32), _rgb565(c1).astype(np.int32)
    four = (c0 > c1)[:, None]
    p2 = np.where(four, (2 * p0 + p1) // 3, (p0 + p1) // 2)
    p3 = np.where(four, (p0 + 2 * p1) // 3, 0)
    p3[:, 3] = np.where(four[:, 0], 255, 0)
    palette = np.stack([p0, p1, p2, p3], 1).astype(np.uint8)  # (count, 4, 4)
    bits = blocks[:, 4:8]
    index = np.stack([(bits >> s) & 3 for s in (6, 4, 2, 0)], -1).reshape(count, 16)  # row by row, MSB first
    pixels = np.take_along_axis(palette, index[:, :, None].repeat(4, 2), 1)  # (count, 16, 4)
    # Four 4x4 sub-blocks per 8x8 tile (top left, top right, bottom left, bottom right).
    sub = pixels.reshape(-1, 2, 2, 4, 4, 4)  # tile, sub y, sub x, y, x, rgba
    tiles = sub.transpose(0, 1, 3, 2, 4, 5).reshape(-1, 64, 4)  # tile, 8x8 pixels row by row
    return _untile(tiles.reshape(-1, 4), w, h, 8, 8)


def decode(fmt: int, w: int, h: int, data: bytes, palette=None, palette_format=0, palette_count=0) -> np.ndarray:
    tw, th = TILE[fmt]
    pw, ph = (w + tw - 1) // tw * tw, (h + th - 1) // th * th
    size = pw * ph * BITS[fmt] // 8
    data = bytes(data[:size]).ljust(size, b"\0")
    if fmt == 14:
        return _cmpr(data, w, h)
    if fmt == 0:
        i = _expand(_nibbles(data), 4)
        px = np.stack([i, i, i, i], -1)
    elif fmt == 1:
        i = np.frombuffer(data, np.uint8)
        px = np.stack([i, i, i, i], -1)
    elif fmt == 2:
        n = _nibbles(data).reshape(-1, 2)
        i, a = _expand(n[:, 1], 4), _expand(n[:, 0], 4)
        px = np.stack([i, i, i, a], -1)
    elif fmt == 3:
        b = np.frombuffer(data, np.uint8).reshape(-1, 2)
        px = np.stack([b[:, 1], b[:, 1], b[:, 1], b[:, 0]], -1)
    elif fmt == 4:
        px = _rgb565(np.frombuffer(data, ">u2"))
    elif fmt == 5:
        px = _rgb5a3(np.frombuffer(data, ">u2"))
    elif fmt == 6:
        b = np.frombuffer(data, np.uint8).reshape(-1, 2, 16, 2)  # tile, AR/GB half, pixel, pair
        a, r, g, bl = b[:, 0, :, 0], b[:, 0, :, 1], b[:, 1, :, 0], b[:, 1, :, 1]
        px = np.stack([r, g, bl, a], -1).reshape(-1, 4)
    elif fmt in (8, 9, 10):
        if fmt == 8:
            idx = _nibbles(data)
        elif fmt == 9:
            idx = np.frombuffer(data, np.uint8)
        else:
            idx = np.frombuffer(data, ">u2") & 0x3FFF
        pal = _palette(palette or b"", palette_format, palette_count) if palette else np.zeros((1, 4), np.uint8)
        px = pal[np.minimum(idx, len(pal) - 1)]
    else:
        raise ValueError(f"unknown GX texture format {fmt}")
    return _untile(px, w, h, tw, th)


def decode_tex1(header: bytes, image: bytes, palette: bytes | None = None) -> np.ndarray:
    fmt, w, h = header[0], *struct.unpack_from(">HH", header, 2)
    palette_format, palette_count = header[9], struct.unpack_from(">H", header, 10)[0]
    return decode(fmt, w, h, image, palette if header[8] else None, palette_format, palette_count)


def texture_entries(tex1: bytes):
    """(name, header, image data, palette data) for each texture of a TEX1 block."""
    count = struct.unpack_from(">H", tex1, 8)[0]
    headers, names_at = struct.unpack_from(">II", tex1, 0x0C)
    names = []
    if names_at:
        n = struct.unpack_from(">H", tex1, names_at)[0]
        for i in range(n):
            at = names_at + struct.unpack_from(">H", tex1, names_at + 6 + 4 * i)[0]
            names.append(tex1[at:tex1.index(b"\0", at)].decode("latin-1"))
    out = []
    for i in range(count):
        at = headers + 32 * i
        header = tex1[at:at + 32]
        fmt, w, h = header[0], *struct.unpack_from(">HH", header, 2)
        tw, th = TILE[fmt]
        size = ((w + tw - 1) // tw * tw) * ((h + th - 1) // th * th) * BITS[fmt] // 8
        image_at = at + struct.unpack_from(">I", header, 0x1C)[0]
        palette = None
        if header[8]:
            palette_at = at + struct.unpack_from(">I", header, 0x0C)[0]
            palette = tex1[palette_at:palette_at + 2 * struct.unpack_from(">H", header, 10)[0]]
        out.append((names[i] if i < len(names) else f"tex{i}", header, tex1[image_at:image_at + size], palette))
    return out


def write_png(path, rgba: np.ndarray):
    h, w = rgba.shape[:2]
    raw = b"".join(b"\0" + rgba[y].astype(np.uint8).tobytes() for y in range(h))

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
                           chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def main(argv) -> int:
    if len(argv) != 3 or argv[0] != "dump":
        print(__doc__)
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from j3d_mesh import Model, load_model_bytes
    model = Model(load_model_bytes(Path(argv[1]))[0])
    out = Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for i, (name, header, image, palette) in enumerate(texture_entries(model.blocks["TEX1"])):
        write_png(out / f"{i:02d}_{name}.png", decode_tex1(header, image, palette))
        print(f"{i:02d} {name} format {header[0]} {struct.unpack_from('>HH', header, 2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

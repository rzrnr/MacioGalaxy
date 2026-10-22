"""The star model with a purple texture in its unused colour slot (native/CUSTOM_GALAXY.md).

PowerStar.arc's BTP animation picks the star's texture by colour: frame 0 yellow, 2 green, 3 red;
frame 1's texture (PowerStar.1) is never chosen by the game. This copy makes it a purple version of
the yellow star's shading (same 16x16 CMPR size); the port shows frame 1 for the stars of mods'
galaxies (src/Game/MapObj/PowerStar.cpp). Everything else stays byte for byte.
"""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from stage_edit import Archive, yaz0_compress  # noqa: E402


def c565(v):
    return ((v >> 11 & 31) * 255 // 31, (v >> 5 & 63) * 255 // 63, (v & 31) * 255 // 31)


def to565(r, g, b):
    return (round(r * 31 / 255) << 11) | (round(g * 63 / 255) << 5) | round(b * 31 / 255)


def purple(rgb):
    """The yellow ramp's brightness on a purple ramp."""
    light = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) / 255
    return (min(255, 200 * light + 40), min(255, 60 * light), min(255, 255 * light + 30))


def purple_power_star(raw: bytes) -> bytes:
    archive = Archive(raw)
    index = [i for path, i in archive.files.items() if path.endswith("powerstar.bdl")][0]
    model = bytearray(archive.contents[index])
    tex1 = model.find(b"TEX1")

    def texture(slot):
        header = tex1 + 0x20 + slot * 32
        return header + struct.unpack_from(">I", model, header + 0x1C)[0]

    source, target = texture(1), texture(2)  # PowerStar.0 (yellow) -> PowerStar.1 (unused)
    for block in range(0, 128, 8):  # CMPR: 8-byte blocks of two RGB565 colours and 2-bit indices
        c0, c1 = struct.unpack_from(">HH", model, source + block)
        indices = model[source + block + 4:source + block + 8]
        n0, n1 = to565(*purple(c565(c0))), to565(*purple(c565(c1)))
        if (c0 > c1) != (n0 > n1) or n0 == n1:  # keep the block's four- or three-colour mode
            n0, n1 = (n0, n1) if c0 > c1 else (n1, n0)
            if c0 > c1 and n0 <= n1:
                n0, n1 = max(n0, n1 + 1), min(n0, n1)
        struct.pack_into(">HH", model, target + block, n0, n1)
        model[target + block + 4:target + block + 8] = indices
    archive.contents[index] = bytes(model)
    return yaz0_compress(archive.build())

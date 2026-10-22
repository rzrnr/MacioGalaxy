"""The mods' theme colour, hazelnut brown (#8A5A32): the stars of mods' galaxies, their counter and
the mods' own Launch Stars (native/CUSTOM_GALAXY.md, "The theme colour").

Every file here is a copy of a disc file with textures turned hazelnut, written into a mod's files/
by the mods' build scripts (GuglisPlanet/build.py, Whitehole's game_export_mod); the disc is only read.
Each change uses a slot the game itself leaves unused, so the original look stays where it was:

- ObjectData/PowerStar.arc: the star's texture for BTP frame 1 (PowerStar.1, never chosen by the
  game) becomes a hazelnut star; the port shows frame 1 for the stars of mods' galaxies.
- LayoutData/GuglisStars.arc: StarCounter.arc renamed (both names have 11 letters, so only the names
  change), with a hazelnut star icon: the counter of those stars (src/Game/Screen/ModStarCounter.cpp).
- ObjectData/SuperSpinDriver.arc: texture slot 3 (an unused copy of the yellow star's) gets its own
  hazelnut image and BTP frame 3 (the animation made one frame longer) shows it; hazel.brk (yellow.brk's shimmer) goes with it. Placed as
  SuperSpinDriverHazel, a Launch Star is hazelnut (src/Game/MapObj/SuperSpinDriver.cpp).
- ObjectData/SpinDriverPath.arc: hazel.bti, the dotted flight path of those Launch Stars.

    python3 native/mods/theme.py FILES_DIR [--disc DIR]   writes the four files into FILES_DIR
"""
import argparse
import colorsys
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from make_example_galaxy import renamed_archive  # noqa: E402
from rarc_write import make_rarc  # noqa: E402
from stage_edit import Archive, yaz0_compress  # noqa: E402

HAZEL = (0x8A, 0x5A, 0x32)
HUE = colorsys.rgb_to_hsv(*(c / 255 for c in HAZEL))[0]  # about 0.075
COUNTER_LAYOUT = "GuglisStars"  # same length as StarCounter
LAUNCH_SLOT = 3  # SuperSpinDriver's spare texture slot and BTP frame


def hazel(rgb, saturation=0.66, value=0.62):
    """A colour (0..1 floats) on the hazelnut ramp: the theme's hue, its saturation and brightness scaled."""
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    if s < 0.12:
        return rgb  # white highlights and grey stay
    return colorsys.hsv_to_rgb(HUE, min(1.0, s * saturation), min(1.0, v * value))


# ---- texture formats ------------------------------------------------------------------------


def rgb565(value):
    return ((value >> 11 & 31) / 31, (value >> 5 & 63) / 63, (value & 31) / 31)


def to565(rgb):
    r, g, b = (min(1.0, max(0.0, c)) for c in rgb)
    return round(r * 31) << 11 | round(g * 63) << 5 | round(b * 31)


def recolour_cmpr(data: bytearray, source: int, target: int, size: int, **ramp):
    """CMPR (S3TC-like) blocks from source to target, recoloured; each block keeps its mode."""
    for block in range(0, size, 8):
        c0, c1 = struct.unpack_from(">HH", data, source + block)
        n0, n1 = to565(hazel(rgb565(c0), **ramp)), to565(hazel(rgb565(c1), **ramp))
        if c0 > c1 and n0 <= n1:  # four-colour block: keep c0 > c1
            n0, n1 = (n1, n0) if n1 > n0 else (min(0xFFFF, n0 + 1), n1)
        elif c0 <= c1 and n0 > n1:  # three-colour block with transparency: keep c0 <= c1
            n0, n1 = n1, n0
        struct.pack_into(">HH", data, target + block, n0, n1)
        data[target + block + 4:target + block + 8] = data[source + block + 4:source + block + 8]


def recolour_rgb5a3(data: bytearray, start: int, pixels: int, **ramp):
    for at in range(start, start + 2 * pixels, 2):
        value = struct.unpack_from(">H", data, at)[0]
        if value & 0x8000:
            r, g, b = hazel([(value >> shift & 31) / 31 for shift in (10, 5, 0)], **ramp)
            value = 0x8000 | round(r * 31) << 10 | round(g * 31) << 5 | round(b * 31)
        else:
            r, g, b = hazel([(value >> shift & 15) / 15 for shift in (8, 4, 0)], **ramp)
            value = (value & 0x7000) | round(r * 15) << 8 | round(g * 15) << 4 | round(b * 15)
        struct.pack_into(">H", data, at, value)


def tex1_images(model: bytes):
    """(format, width, height, data offset) of each texture of a J3D model's TEX1."""
    tex1 = model.find(b"TEX1")
    count = struct.unpack_from(">H", model, tex1 + 8)[0]
    headers = tex1 + struct.unpack_from(">I", model, tex1 + 0x0C)[0]
    images = []
    for slot in range(count):
        header = headers + slot * 32
        fmt = model[header]
        width, height = struct.unpack_from(">HH", model, header + 2)
        images.append((fmt, width, height, header + struct.unpack_from(">I", model, header + 0x1C)[0]))
    return images


def archive_file(archive: Archive, suffix: str) -> int:
    return [index for path, index in archive.files.items() if path.endswith(suffix)][0]


# ---- the files ------------------------------------------------------------------------------


def theme_power_star(raw: bytes) -> bytes:
    archive = Archive(raw)
    index = archive_file(archive, "powerstar.bdl")
    model = bytearray(archive.contents[index])
    images = tex1_images(model)
    fmt, width, height, yellow = images[1]  # PowerStar.0 (yellow) -> PowerStar.1 (unused)
    recolour_cmpr(model, yellow, images[2][3], width * height // 2)
    archive.contents[index] = bytes(model)
    return yaz0_compress(archive.build())


def theme_star_counter(raw: bytes) -> bytes:
    archive = Archive(renamed_archive(raw, "StarCounter", COUNTER_LAYOUT))
    index = archive.find("timg/imiconstar.tpl")
    tpl = bytearray(archive.contents[index])
    count, table = struct.unpack_from(">II", tpl, 4)
    for image in range(count):
        header = struct.unpack_from(">I", tpl, table + 8 * image)[0]
        height, width, fmt, offset = struct.unpack_from(">HHII", tpl, header)
        if fmt != 5:
            raise ValueError(f"ImIconStar.tpl: image format {fmt}, expected RGB5A3 (5)")
        recolour_rgb5a3(tpl, offset, (width + 3) // 4 * 4 * ((height + 3) // 4 * 4), value=0.72)
    archive.contents[index] = bytes(tpl)
    return yaz0_compress(archive.build())


def theme_launch_star(raw: bytes) -> bytes:
    archive = Archive(raw)
    files = {path: archive.contents[index] for path, index in archive.files.items()}
    model = bytearray(files["superspindriver.bdl"])
    images = tex1_images(model)
    fmt, width, height, yellow = images[0]
    if fmt != 14 or images[LAUNCH_SLOT][0] != 14:
        raise ValueError("SuperSpinDriver.bdl: expected CMPR textures")
    # Slot 3 shares slot 0's image data: give it its own copy at the end of TEX1 (the last block).
    size = width * height // 2
    tex1 = model.find(b"TEX1")
    if tex1 + struct.unpack_from(">I", model, tex1 + 4)[0] != len(model):
        raise ValueError("SuperSpinDriver.bdl: TEX1 is not the last block")
    model += bytes(-len(model) % 32)
    own = len(model)
    model += bytes(size)
    header = tex1 + struct.unpack_from(">I", model, tex1 + 0x0C)[0] + LAUNCH_SLOT * 32
    struct.pack_into(">I", model, header + 0x1C, own - header)
    struct.pack_into(">I", model, tex1 + 4, len(model) - tex1)
    struct.pack_into(">I", model, 8, len(model))
    recolour_cmpr(model, yellow, own, size)
    files["superspindriver.bdl"] = bytes(model)
    # BTP: frame 3 of each material shows texture 3 (the table is 0, 1, 2, 2 on the disc).
    btp = bytearray(files["superspindriver.btp"])
    tpt1 = btp.find(b"TPT1")
    indices = tpt1 + struct.unpack_from(">I", btp, tpt1 + 0x14)[0]
    if struct.unpack_from(">4H", btp, indices) != (0, 1, 2, 2):
        raise ValueError("SuperSpinDriver.btp: unexpected texture table")
    struct.pack_into(">H", btp, indices + 2 * LAUNCH_SLOT, LAUNCH_SLOT)
    # The animation is 3 frames long, and a stopped animation is held just below its end (frame 2.999,
    # pink): 4 frames, so that frame 3 is shown.
    if struct.unpack_from(">H", btp, tpt1 + 0x0A)[0] != 3:
        raise ValueError("SuperSpinDriver.btp: unexpected length")
    struct.pack_into(">H", btp, tpt1 + 0x0A, LAUNCH_SLOT + 1)
    files["superspindriver.btp"] = bytes(btp)
    files["hazel.brk"] = files["yellow.brk"]  # the yellow star's shimmer suits a warm colour
    return yaz0_compress(make_rarc("superspindriver", files))


def theme_launch_path(raw: bytes) -> bytes:
    archive = Archive(raw)
    files = {path: archive.contents[index] for path, index in archive.files.items()}
    bti = bytearray(files["pink.bti"])
    fmt, width, height = bti[0], *struct.unpack_from(">HH", bti, 2)
    if fmt != 5:
        raise ValueError("SpinDriverPath pink.bti: expected RGB5A3")
    recolour_rgb5a3(bti, struct.unpack_from(">I", bti, 0x1C)[0], width * height, saturation=0.9, value=0.8)
    files["hazel.bti"] = bytes(bti)
    return yaz0_compress(make_rarc("spindriverpath", files))


def write_theme(files_dir: Path, disc: Path):
    """The theme's files into a mod's files/ (disc: the extracted disc's files/)."""
    (files_dir / "ObjectData").mkdir(parents=True, exist_ok=True)
    (files_dir / "LayoutData").mkdir(parents=True, exist_ok=True)
    (files_dir / "ObjectData/PowerStar.arc").write_bytes(theme_power_star((disc / "ObjectData/PowerStar.arc").read_bytes()))
    (files_dir / f"LayoutData/{COUNTER_LAYOUT}.arc").write_bytes(theme_star_counter((disc / "LayoutData/StarCounter.arc").read_bytes()))
    (files_dir / "ObjectData/SuperSpinDriver.arc").write_bytes(theme_launch_star((disc / "ObjectData/SuperSpinDriver.arc").read_bytes()))
    (files_dir / "ObjectData/SpinDriverPath.arc").write_bytes(theme_launch_path((disc / "ObjectData/SpinDriverPath.arc").read_bytes()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", type=Path)
    parser.add_argument("--disc", type=Path, default=Path.home() / "Library/Application Support/Petari/Disc/RMGE01")
    args = parser.parse_args()
    disc = args.disc / "files" if (args.disc / "files").is_dir() else args.disc
    write_theme(args.files, disc)
    print(f"Wrote the theme's files into {args.files}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

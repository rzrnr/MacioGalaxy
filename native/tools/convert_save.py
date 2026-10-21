#!/usr/bin/env python3
"""Convert Super Mario Galaxy saves between this port and the Wii's format.

The native app writes GameData.bin with the game's own code, so its multi-byte
fields are in the Mac's little-endian order; the Wii, Dolphin and Nebula keep
the same file in big-endian order. The layouts are the same: this tool swaps
every field by its width, as the game's serializers write them, and
recomputes the checksum (MR::calcCheckSum over u16 words).

  convert_save.py inspect FILE           which order FILE is in, and its files
  convert_save.py to-wii IN OUT          native save -> Wii order (Dolphin, Nebula)
  convert_save.py to-native IN OUT       Wii order -> native save
  convert_save.py export OUT             your native save -> OUT in Wii order
  convert_save.py bundle [OUT.zip]       one file to send: your save in Wii order,
                                         guglis/SPIELSTAND_WINDOWS.md and this tool
                                         (default: Desktop, dated)
  convert_save.py bundle --from FILE [OUT.zip]
                                         the same for any save, e.g. Nebula's on
                                         Windows (a Wii-order file goes in as is)
  convert_save.py import IN              a Wii-order save (or a bundle zip) -> your
                                         native save (quit the game first; the old
                                         save is kept in save-backups)

import and export work on the Mac's save; inspect, to-wii, to-native and
bundle --from work anywhere Python 3 runs, Windows included.

Where the Wii-order file goes (US disc, RMGE01):
  Dolphin:  <Dolphin user dir>/Wii/title/00010000/524d4745/data/GameData.bin
  Nebula:   %LOCALAPPDATA%\\Nebula\\saves\\title\\00010000\\524d4745\\data\\GameData.bin

Every conversion is checked by converting the result back: it must give the
input byte for byte. banner.bin (the Wii Menu's save icon) is not converted;
the game writes it again when it saves.
"""
import argparse
import datetime
import shutil
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

USER = Path.home() / "Library/Application Support/Petari"
SAVE_RELATIVE = Path("NAND/title/00010000/524d4745/data/GameData.bin")
FILE_VERSION = 2
FILE_ENTRIES = 19
LE, BE = "<", ">"


class Swapper:
    """Copies a save and swaps its fields from one byte order to the other."""

    def __init__(self, data: bytes, src: str):
        self.src = src
        self.dst = BE if src == LE else LE
        self.out = bytearray(data)
        self.data = data

    def read(self, fmt: str, offset: int):
        return struct.unpack_from(self.src + fmt, self.data, offset)

    def swap(self, fmt: str, offset: int):
        values = self.read(fmt, offset)
        struct.pack_into(self.dst + fmt, self.out, offset, *values)
        return values

    def swap_array(self, width: int, start: int, end: int):
        if (end - start) % width:
            raise ValueError(f"{end - start} bytes at {start:#x} are no whole {width}-byte fields")
        code = {2: "H", 4: "I", 8: "Q"}[width]
        for offset in range(start, end, width):
            self.swap(code, offset)


def content_attributes(sw: Swapper, start: int):
    """BinaryDataContentHeaderSerializer: u16 count, u16 record size, (u16 hash, u16 offset) each.
    Returns [(offset, width)] sorted by offset, the record size, and the header's end."""
    count, record_size = sw.swap("HH", start)
    offsets = []
    for index in range(count):
        _hash, offset = sw.swap("HH", start + 4 + index * 4)
        offsets.append(offset)
    offsets.sort()
    widths = [(offset, (offsets[i + 1] if i + 1 < len(offsets) else record_size) - offset) for i, offset in enumerate(offsets)]
    return widths, record_size, start + 4 + count * 4


def swap_record(sw: Swapper, start: int, widths, element_of):
    for offset, width in widths:
        element = element_of(width)
        if element > 1:
            sw.swap_array(element, start + offset, start + offset + width)


def swap_spin_driver(sw: Swapper, start: int, end: int):
    """SPN1 (SpinDriverPathStorage): u8 galaxy count; per galaxy u16 hash, u16 block size, u8 scenario
    count, u8 0, then per scenario u16 block size and single bytes."""
    position = start + 1
    for _ in range(sw.data[start]):
        _hash, block = sw.swap("HH", position)
        scenarios = sw.data[position + 4]
        at = position + 6
        for _ in range(scenarios):
            (size,) = sw.swap("H", at)
            at += size
        if at != position + block:
            raise ValueError(f"SPN1: galaxy block at {position:#x} is {block} bytes, its scenarios {at - position}")
        position += block
    if position > end:
        raise ValueError("SPN1 overruns its chunk")


def swap_chunk(sw: Swapper, signature: str, start: int, end: int):
    if signature == "PLAY":  # u8 story progress, u32 stocked Star Bits, u16 lives
        if end - start != 7:
            raise ValueError(f"PLAY is {end - start} bytes")
        sw.swap("I", start + 1)
        sw.swap("H", start + 5)
    elif signature in ("FLG1", "PCE1", "VLE1"):  # u16 words: flags, Star Bit counts, (hash, value) pairs
        sw.swap_array(2, start, end)
    elif signature == "SPN1":
        swap_spin_driver(sw, start, end)
    elif signature == "GALA":  # u16 galaxy count, content header, records (names u16, coin counts u16[8])
        (galaxies,) = sw.swap("H", start)
        widths, record_size, records = content_attributes(sw, start + 2)
        if records + galaxies * record_size != end:
            raise ValueError(f"GALA: {galaxies} records of {record_size} bytes do not fill the chunk")
        for index in range(galaxies):
            swap_record(sw, records + index * record_size, widths, lambda width: 1 if width == 1 else 2)
    elif signature == "SYSC":  # content header, one record (OSTime, OSTime, u32)
        widths, record_size, record = content_attributes(sw, start)
        if record + record_size != end:
            raise ValueError("SYSC record does not fill the chunk")
        swap_record(sw, record, widths, lambda width: width)
    elif signature == "MISC":  # u8 flag, OSTime last modified
        if end - start != 9:
            raise ValueError(f"MISC is {end - start} bytes")
        sw.swap("Q", start + 1)
    elif signature in ("CONF", "MII "):  # single bytes (the Mii's create ID is a byte array)
        pass
    else:
        raise ValueError(f"unknown chunk {signature!r}")


def swap_holder(sw: Swapper, start: int, end: int):
    """BinaryDataChunkHolder: u8 1, u8 chunk count, 2 pad; chunks of u32 signature, u32 hash,
    u32 size (with this 12-byte header), payload. An all-zero entry is an unused file."""
    if not any(sw.data[start:end]):
        return
    if sw.data[start] != 1:
        raise ValueError(f"entry at {start:#x} starts {sw.data[start:start + 4].hex()}")
    offset = start + 4
    for _ in range(sw.data[start + 1]):
        signature, _hash, size = sw.swap("III", offset)
        if size < 12 or offset + size > end:
            raise ValueError(f"chunk at {offset:#x} has size {size:#x}")
        swap_chunk(sw, signature.to_bytes(4, "big").decode("latin-1"), offset + 12, offset + size)
        offset += size


def check_sum(data: bytes, order: str) -> int:
    total = inverse = 0
    for (word,) in struct.iter_unpack(order + "H", data[: len(data) // 2 * 2]):
        total = (total + word) & 0xFFFF
        inverse = (inverse + (~word & 0xFFFF)) & 0xFFFF
    return total << 16 | inverse


def byte_order(data: bytes) -> str:
    for order in (LE, BE):
        if len(data) >= 16:
            _sum, version, count, size = struct.unpack_from(order + "4I", data, 0)
            if version == FILE_VERSION and count == FILE_ENTRIES and size <= len(data):
                return order
    raise ValueError("not a Super Mario Galaxy GameData.bin (version 2, 19 files) in either byte order")


def check(data: bytes, order: str) -> list:
    stored, _version, count, size = struct.unpack_from(order + "4I", data, 0)
    if check_sum(data[4:size], order) != stored:
        raise ValueError(f"checksum {stored:#010x} does not match the contents ({check_sum(data[4:size], order):#010x})")
    names = []
    for index in range(count):
        name, offset = struct.unpack_from(order + "12sI", data, 16 + index * 16)
        names.append((name.split(b"\0", 1)[0].decode("ascii"), offset))
    return names


def convert(data: bytes) -> bytes:
    src = byte_order(data)
    names = check(data, src)
    sw = Swapper(data, src)
    _sum, _version, count, size = sw.swap("4I", 0)
    for index in range(count):
        sw.swap("I", 16 + index * 16 + 12)
    ordered = sorted(names, key=lambda item: item[1])
    for position, (name, offset) in enumerate(ordered):
        end = ordered[position + 1][1] if position + 1 < len(ordered) else size
        try:
            swap_holder(sw, offset, end)
        except ValueError as error:
            raise ValueError(f"{name}: {error}") from None
    struct.pack_into(sw.dst + "I", sw.out, 0, check_sum(bytes(sw.out[4:size]), sw.dst))
    return bytes(sw.out)


def convert_checked(data: bytes, want: str) -> bytes:
    if byte_order(data) == want:
        raise ValueError("the file is already in that byte order")
    out = convert(data)
    check(out, want)
    if convert(out) != data:
        raise ValueError("converting the result back does not give the input; nothing written")
    return out


def describe(data: bytes) -> str:
    order = byte_order(data)
    names = check(data, order)
    used = [name for name, offset in names if name != "sysconf" and any(data[offset:offset + 4])]
    kind = "native (little-endian, this port)" if order == LE else "Wii (big-endian: Wii, Dolphin, Nebula)"
    return f"{kind}; files in use: {', '.join(used) or 'none'}"


def write_new(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".converting")
    temporary.write_bytes(data)
    temporary.replace(path)


def write_bundle(save: Path, output: Path) -> bytes:
    """A zip with the save in Wii order (as GameData.bin), the Windows guide and this tool. A save
    already in Wii order (Nebula's, Dolphin's) goes in as it is, after the format check."""
    data = save.read_bytes()
    if byte_order(data) == BE:
        check(data, BE)
        wii, origin = data, "Wii-Format (Nebula, Dolphin)"
    else:
        wii, origin = convert_checked(data, BE), "Mac (MacioGalaxy)"
    here = Path(__file__).resolve()
    guides = [here.parents[2] / "guglis/SPIELSTAND_WINDOWS.md", here.parent / "SPIELSTAND_WINDOWS.md"]
    guide = next((path for path in guides if path.is_file()), None)
    saved = datetime.datetime.fromtimestamp(save.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    note = (f"Super Mario Galaxy: Spielstand aus {origin}, zuletzt im Spiel gespeichert {saved}.\n"
            f"{describe(wii)}\n\n"
            "GameData.bin ist im Wii-Format (Nebula, Dolphin, Wii). In Nebula: hineinkopieren, siehe\n"
            "SPIELSTAND_WINDOWS.md. Auf dem Mac: convert_save.py import <diese ZIP>.\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".writing")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("GameData.bin", wii)
        archive.writestr("LIESMICH.txt", note)
        if guide is not None:
            archive.write(guide, "SPIELSTAND_WINDOWS.md")
        archive.write(here, "convert_save.py")
    temporary.replace(output)
    return wii


def game_running() -> bool:
    """Whether the Mac app runs (only asked on the Mac: elsewhere there is none to quit)."""
    if sys.platform != "darwin":
        return False
    try:
        return subprocess.run(["pgrep", "-x", "Petari"], capture_output=True).returncode == 0
    except OSError:
        return False


def read_save(path: Path) -> bytes:
    """A GameData.bin, or the one inside a bundle zip."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.rsplit("/", 1)[-1] == "GameData.bin"]
            if len(names) != 1:
                raise ValueError(f"{path} holds {len(names)} GameData.bin files, not one")
            return archive.read(names[0])
    return path.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", type=Path, default=USER, help="the port's user directory (for export and import)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect").add_argument("file", type=Path)
    for name in ("to-wii", "to-native"):
        sub = commands.add_parser(name)
        sub.add_argument("input", type=Path)
        sub.add_argument("output", type=Path)
    commands.add_parser("export").add_argument("output", type=Path)
    bundle = commands.add_parser("bundle")
    bundle.add_argument("--from", dest="source", type=Path, help="this save instead of the Mac's")
    bundle.add_argument("output", type=Path, nargs="?")
    commands.add_parser("import").add_argument("input", type=Path)
    args = parser.parse_args()
    save = args.user / SAVE_RELATIVE
    try:
        if args.command == "inspect":
            print(describe(args.file.read_bytes()))
        elif args.command in ("to-wii", "to-native", "export"):
            source = save if args.command == "export" else args.input
            want = LE if args.command == "to-native" else BE
            write_new(args.output, convert_checked(source.read_bytes(), want))
            print(f"Wrote {args.output}: {describe(args.output.read_bytes())}")
        elif args.command == "bundle":
            output = args.output or Path.home() / "Desktop" / f"Mario Galaxy Spielstand{' Windows' if args.source else ''} {time.strftime('%Y-%m-%d %H-%M')}.zip"
            wii = write_bundle(args.source or save, output)
            print(f"Wrote {output}: {describe(wii)}")
            if args.source is None and game_running():
                print("Note: the game is running; this is the save as last written by the game.")
        elif args.command == "import":
            if game_running():
                raise ValueError("Super Mario Galaxy is running; quit it first")
            out = convert_checked(read_save(args.input), LE)
            if save.exists():
                backups = args.user / "save-backups"
                backups.mkdir(exist_ok=True)
                backup = backups / f"GameData.bin.before-import-{time.strftime('%Y%m%d-%H%M%S')}"
                shutil.copy2(save, backup)
                print(f"Backup of the previous save: {backup}")
            write_new(save, out)
            print(f"Installed {save}: {describe(out)}")
    except (OSError, ValueError) as error:
        print(f"convert_save: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

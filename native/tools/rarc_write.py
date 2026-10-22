#!/usr/bin/env python3
"""Write a new RARC archive with one folder of files (native/CUSTOM_GALAXY.md).

The game's object archives (ObjectData/<Name>.arc) are one folder named like the object in lower
case, holding <name>.bdl, .kcl, .pa and the like. stage_edit.Archive replaces files inside an
existing archive; this makes a new one under any name:

    make_rarc("guglisplanetsphere", {"guglisplanetsphere.bdl": data, ...}) -> bytes (plain RARC)

Layout as on the disc: a 0x20 header, the info block, the folder node, the entries (the files,
then "." and ".."), the string table (".", "..", the folder, the files), and the file data, each
32-byte aligned; every file is preloaded to main memory (flags 0x11).

    rarc_write.py selftest   rebuilds a disc archive's files with it and reads them back
"""
import struct
import sys
from pathlib import Path


def name_hash(name: str) -> int:
    value = 0
    for byte in name.encode("latin-1"):
        value = (value * 3 + byte) & 0xFFFF
    return value


def align(length: int, to: int = 32) -> int:
    return (length + to - 1) // to * to


def make_rarc(folder: str, files: dict) -> bytes:
    names = list(files)
    strings = bytearray(b".\0..\0")
    offsets = {}
    for name in [folder] + names:
        offsets[name] = len(strings)
        strings += name.encode("latin-1") + b"\0"
    strings += bytes(align(len(strings)) - len(strings))

    entry_count = len(names) + 2
    node_offset = 0x20  # relative to the info block at 0x20
    entry_offset = node_offset + align(16)
    string_offset = entry_offset + align(entry_count * 20)
    data_offset = string_offset + len(strings)

    data = bytearray()
    positions = []
    for name in names:
        positions.append(len(data))
        data += files[name]
        data += bytes(align(len(data)) - len(data))

    entries = bytearray()
    for index, name in enumerate(names):
        entries += struct.pack(">HHBBHIII", index, name_hash(name), 0x11, 0, offsets[name], positions[index], len(files[name]), 0)
    entries += struct.pack(">HHBBHIII", 0xFFFF, name_hash("."), 0x02, 0, 0, 0, 0x10, 0)
    entries += struct.pack(">HHBBHIII", 0xFFFF, name_hash(".."), 0x02, 0, 2, 0xFFFFFFFF, 0x10, 0)
    entries += bytes(align(len(entries)) - len(entries))

    info = struct.pack(">6IHBB", 1, node_offset, entry_count, entry_offset, len(strings), string_offset, len(names), 1, 0)
    info += bytes(node_offset - len(info))
    node = struct.pack(">4sIHHI", b"ROOT", offsets[folder], name_hash(folder), entry_count, 0)
    node += bytes(align(len(node)) - len(node))

    body = info + node + entries + bytes(strings)
    assert len(body) == data_offset
    total = 0x20 + data_offset + len(data)
    header = struct.pack(">4s7I", b"RARC", total, 0x20, data_offset, len(data), len(data), 0, 0)
    return header + body + bytes(data)


def selftest() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from stage_edit import Archive

    disc = Path.home() / "Library/Application Support/Petari/Disc/RMGE01/files/ObjectData"
    source = Archive((disc / "StardustHillPlanet.arc").read_bytes())
    files = {path: source.contents[index] for path, index in source.files.items()}  # paths below the folder
    built = Archive(make_rarc("guglistest", files))
    rebuilt = {path: built.contents[index] for path, index in built.files.items()}
    assert rebuilt == files, "files differ"
    assert built._string(struct.unpack_from(">I", built.data, 0x40 + 4)[0]) == "guglistest", "folder name"
    print(f"rarc_write selftest: {len(files)} files rebuilt and read back")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if sys.argv[1:] == ["selftest"] else (print(__doc__) or 0))

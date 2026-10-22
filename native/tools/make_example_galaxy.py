#!/usr/bin/env python3
"""Build the example galaxy mod (native/CUSTOM_GALAXY.md) from your own copy of the disc.

A new galaxy, "Guglis Testgalaxie" (ExampleGalaxy), entered from the Comet Observatory's first
dome like the game's own: a sixth miniature next to Good Egg, Honeyhive, Loopdeeloop, Flipswitch
and Bowser Jr.'s Robot Reactor. Its level is Sweet Sweet Galaxy's (BeltConveyerExGalaxy) under
the new name, with a new Toad who talks at the start and three GuglisSpinBox objects, the
example of new logic (src/Game/MapObj/GuglisSpinBox.cpp). Every Toad says new lines from the
mod's messages.txt.

The disc is only read. The mod is written to <user>/mods/ExampleGalaxy (replaced as a whole when
it exists). It holds files derived from the disc, so it stays on this machine; this script and
the text are what the repository keeps. Turn it on in F1 -> Mods -> Mod folder, or for one run:
PETARI_MOD_FOLDERS=ExampleGalaxy.

  python3 native/tools/make_example_galaxy.py [--disc DIR] [--user DIR]
"""
import argparse
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stage_edit import Archive, StageEdit, jmap_hash, yaz0_compress  # noqa: E402

TEMPLATE = "BeltConveyerExGalaxy"  # Sweet Sweet Galaxy: one scenario, one zone, the common layer only
GALAXY = "ExampleGalaxy"
MINI_TEMPLATE = "MiniEggStarGalaxy"  # same length as MiniExampleGalaxy: names change in place
MOD = "ExampleGalaxy"

MOD_TXT = f"""name=Guglis Testgalaxie
description=Beispiel einer eigenen Galaxie: Eingang in der ersten Kuppel, neuer Toad mit Dialog, neue Drehkisten
priority=0
{GALAXY}.sound={TEMPLATE}
"""

# Line breaks (\\n) by hand: a balloon shows three lines; [page] starts the next one.
MESSAGES = f"""# Texts of the example galaxy (native/CUSTOM_GALAXY.md): ID = text.
GalaxyName_{GALAXY} = Guglis Testgalaxie
GalaxyNameShort_{GALAXY} = Guglis Testgalaxie
ScenarioName_{GALAXY}1 = Die tanzenden Kisten

# The new Toad at the start (MessageId 5).
{GALAXY}_Kinopio005 = Willkommen in Guglis Testgalaxie![page]Diese Galaxie gibt es nur als Mod.\\nSie ist da, weil du sie im\\nMods-Menu eingeschaltet hast.[page]Siehst du die schwebenden Kisten?\\nDreh dich bei ihnen, dann\\ngeben sie dir Münzen.[page]Nach ein paar Drehungen platzen sie\\nmit einem ganzen Münzregen.\\nViel Spass!
# Sweet Sweet Galaxy's own Toads keep their places and get new lines.
{GALAXY}_Kinopio000 = Hier ist alles neu, aber\\nirgendwie auch nicht.
{GALAXY}_Kinopio001 = Pass auf die Stromschienen auf!
{GALAXY}_Kinopio002 = Der Stern ist ganz am Ende.\\nDu schaffst das!
{GALAXY}_Kinopio003 = Ich warte hier, bis du\\nden Stern hast.
{GALAXY}_Kinopio004 = Fast geschafft!\\nDer Stern ist gleich da vorne.
"""

# Mario starts at (-50, 50, -50) on a wide platform (its ground is at y 45); the bridge ahead (-z)
# starts behind a gap, so the Toad and the boxes stay on the platform, where the coins land.
NEW_TOAD = (250.0, 45.0, 150.0)
SPIN_BOXES = [((-400.0, 200.0, 520.0), 5), ((400.0, 200.0, 520.0), 3), ((0.0, 220.0, 380.0), 1)]
# The sixth miniature in dome 1 (AstroDome, layer A), between the dome's own.
MINI_POSITION = (-3800.0, 175.0, -1450.0)


def rarc_hash(name: str) -> int:
    value = 0
    for char in name.encode():
        value = (value * 3 + char) & 0xFFFF
    return value


def renamed_archive(data: bytes, old: str, new: str) -> bytes:
    """An archive with every entry and folder named old renamed to new (same length): the string
    table and the RARC name hashes, which JKRArchive compares too."""
    if len(old) != len(new):
        raise ValueError("names must have the same length")
    archive = Archive(data)
    out = bytearray(archive.data)
    strings = bytes(out[archive.string_offset:archive.payload])
    out[archive.string_offset:archive.payload] = strings.replace(old.lower().encode(), new.lower().encode())
    header = 0x20
    nodes, node_offset = struct.unpack_from(">II", out, header)
    for index in range(nodes):  # type, name offset, name hash
        at = header + node_offset + index * 16
        name_offset = struct.unpack_from(">I", out, at + 4)[0]
        start = archive.string_offset + name_offset
        struct.pack_into(">H", out, at + 8, rarc_hash(out[start:out.index(0, start)].decode()))
    entries, entry_offset = struct.unpack_from(">II", out, header + 8)
    for index in range(entries):  # id, name hash, type, name offset
        at = header + entry_offset + index * 20
        name_offset = struct.unpack_from(">H", out, at + 6)[0]
        start = archive.string_offset + name_offset
        struct.pack_into(">H", out, at + 2, rarc_hash(out[start:out.index(0, start)].decode()))
    return yaz0_compress(bytes(out))


def build(disc: Path, mod: Path):
    files = mod / "files"
    stages = files / "StageData"
    (stages / GALAXY).mkdir(parents=True)
    (files / "ObjectData").mkdir(parents=True)

    # The level: Sweet Sweet Galaxy's, plus a Toad at the start and three spin boxes.
    level = StageEdit((disc / f"StageData/{TEMPLATE}.arc").read_bytes())
    objects = "jmp/placement/common/objinfo"
    toad = level.add(objects, "Kinopio@0", *NEW_TOAD)
    level.table(objects).set(toad, "MessageId", 5)
    for (x, y, z), hits in SPIN_BOXES:
        box = level.new(objects, "GuglisSpinBox", x, y, z)
        level.table(objects).set(box, "Obj_arg0", hits)
    (stages / f"{GALAXY}.arc").write_bytes(level.build(True))

    # Its scenario: the zone renamed; the scenario table's per-zone layer column named after it.
    scenario = StageEdit((disc / f"StageData/{TEMPLATE}/{TEMPLATE}Scenario.arc").read_bytes())
    table = scenario.table("scenariodata.bcsv")
    table.header = bytearray(table.header)
    for index, field in enumerate(table.fields):
        if field[0] == jmap_hash(TEMPLATE):
            struct.pack_into(">I", table.header, 16 + index * 12, jmap_hash(GALAXY))
    scenario.table("zonelist.bcsv").set(0, "ZoneName", GALAXY)
    (stages / GALAXY / f"{GALAXY}Scenario.arc").write_bytes(scenario.build(True))

    # The dome miniature's model: Good Egg's under the new name.
    mini = disc / f"ObjectData/{MINI_TEMPLATE}.arc"
    (files / "ObjectData" / f"Mini{GALAXY}.arc").write_bytes(renamed_archive(mini.read_bytes(), MINI_TEMPLATE, f"Mini{GALAXY}"))

    # Dome 1 (the Terrace) gets the sixth miniature.
    dome = StageEdit((disc / "StageData/AstroDome.arc").read_bytes())
    domes = "jmp/placement/layera/objinfo"
    row = dome.add(domes, f"{MINI_TEMPLATE}@0", *MINI_POSITION)
    dome.table(domes).set(row, "name", f"Mini{GALAXY}")
    (stages / "AstroDome.arc").write_bytes(dome.build(True))

    (mod / "mod.txt").write_text(MOD_TXT, encoding="utf-8")
    (mod / "messages.txt").write_text(MESSAGES, encoding="utf-8")


def main() -> int:
    home = Path.home() / "Library/Application Support/Petari"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--disc", type=Path, default=home / "Disc/RMGE01", help="the extracted disc (containing files/)")
    parser.add_argument("--user", type=Path, default=home, help="the user directory whose mods/ gets the mod")
    args = parser.parse_args()
    disc = args.disc / "files" if (args.disc / "files").is_dir() else args.disc
    if not (disc / f"StageData/{TEMPLATE}.arc").is_file():
        print(f"make_example_galaxy: no {TEMPLATE}.arc under {disc}/StageData (a US disc, RMGE01, is needed)", file=sys.stderr)
        return 1
    mod = args.user / "mods" / MOD
    work = mod.with_name(f".{MOD}.building")
    shutil.rmtree(work, ignore_errors=True)
    try:
        build(disc, work)
    except (OSError, ValueError, KeyError) as error:
        shutil.rmtree(work, ignore_errors=True)
        print(f"make_example_galaxy: {error}", file=sys.stderr)
        return 1
    shutil.rmtree(mod, ignore_errors=True)
    work.replace(mod)
    print(f"Built {mod}. Turn it on in F1 -> Mods -> Mod folder (or PETARI_MOD_FOLDERS={MOD}) and restart the game.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Guglis' sky island for the Comet Observatory (native/CUSTOM_GALAXY.md, "The observatory").

Makes the island model in Blender (island_blender.py) and writes it as an object archive,
ObjectData/GuglisSkyIsland.arc, with Stardust Hill's grass and soil materials and its collision
(the test planet's tools: native/mods/GuglisPlanet/build.py). Placed by name in a stage, a mod's own
object archive is a planet (PlanetMap). The island is placed in the observatory, with its Launch
Stars and the rest, in Whitehole (mac/mcp in the Whitehole fork); --out puts the archive into
Whitehole's game folder so that its editor shows the island.

    python3 native/mods/Sternenschiff/build.py --out DIR [--from-blend] [--blend-out DIR] [--disc DIR]

The disc is only read; the archive is derived from it, so it stays on this machine.
"""
import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("planet_build", HERE.parent / "GuglisPlanet/build.py")
planet = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(planet)

NAME = "GuglisSkyIsland"


def island_archive(disc: Path, blend_dir: Path, from_blend: bool) -> bytes:
    args = [str(planet.BLENDER), "--background", "--python", str(HERE / "island_blender.py"), "--", str(blend_dir)]
    if from_blend:
        args.append("--from-blend")
    subprocess.run(args, check=True, capture_output=True)
    data = np.load(blend_dir / f"{NAME}.npz")
    template = planet.Archive((disc / f"ObjectData/{planet.MODEL_TEMPLATE}.arc").read_bytes())
    template_bdl = template.contents[template.find(f"{planet.MODEL_TEMPLATE.lower()}.bdl")]
    collision_version = template.contents[template.find("collisionversion")]
    parts, positions, names, tri_material = planet.planet_parts(data)
    model = planet.build_model(template_bdl, parts, name=NAME.lower())
    kcl, pa = planet.collision(positions, names, tri_material)
    return planet.object_archive(NAME, {f"{NAME}.bdl": model, f"{NAME}.kcl": kcl, f"{NAME}.pa": pa,
                                        "collisionversion": collision_version})


def main() -> int:
    home = Path.home() / "Library/Application Support/Petari"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="a game folder (files/): the archive goes to its ObjectData")
    parser.add_argument("--disc", type=Path, default=home / "Disc/RMGE01")
    parser.add_argument("--blend-out", type=Path, default=home / "ModSources/Sternenschiff")
    parser.add_argument("--from-blend", action="store_true", help="export the edited .blend in --blend-out")
    args = parser.parse_args()
    disc = args.disc / "files" if (args.disc / "files").is_dir() else args.disc
    target = args.out / "ObjectData" / f"{NAME}.arc"
    target.write_bytes(island_archive(disc, args.blend_out, args.from_blend))
    print(f"Wrote {target}; the island in Blender: {args.blend_out / (NAME + '.blend')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

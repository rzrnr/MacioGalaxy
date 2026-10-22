#!/usr/bin/env python3
"""Build the mod "Guglis Testplanet" (native/CUSTOM_GALAXY.md, "Your own planet").

From the planet made in Blender (planet_blender.py) and your own copy of the disc, it writes
<user>/mods/GuglisPlanet:

- ObjectData/GuglisPlanetSphere.arc: the planet, its model with Stardust Hill's grass, soil and
  cut-stone materials (native/tools/j3d_mesh.py), its collision with matching footsteps
  (native/tools/kcl_write.py);
- ObjectData/MiniGuglisPlanetGalaxy.arc: the same planet as the dome's miniature;
- StageData/GuglisPlanetGalaxy.arc and its scenario: Snow Cap Galaxy's small one-planet stage,
  emptied and rebuilt around the planet: an aurora sky, a point gravity, the game's small-planet
  camera, Mario flown in by the Launch Star rail after an opening camera flight around the planet
  (camera/startscenario1.canm), three GuglisSpinBox objects; once all three have burst a
  GroupSwitchWatcher turns switch 20 on, and GuglisStarAppear brings the scenario's star out above
  the tallest pillar, seen by its own camera, from where it flies down beside the pillar;
- ObjectData/PowerStar.arc: the star model with a purple texture in its unused colour slot, which
  the port shows for the stars of mods' galaxies (purple stars, counted apart from the game's), and
  LayoutData/PurpleStars.arc, their counter under the game's star counter;
- StageData/AstroDome.arc: the Terrace (dome 1) with the planet's miniature, and those of other mods'
  galaxies found in the user directory (only one mod's AstroDome.arc is used);
- messages.txt and mod.txt.

The planet is made by planet_blender.py in Blender (/Applications/Blender.app, run in the background)
and saved as <user>/ModSources/GuglisPlanet/GuglisTestPlanet.blend; edit it there and build again
with --from-blend.

The disc is only read; the mod is derived from it, so it stays on this machine.

    python3 native/mods/GuglisPlanet/build.py [--from-blend] [--blend-out DIR] [--disc DIR] [--user DIR]
"""
import argparse
import math
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from j3d_mesh import Part, build_model  # noqa: E402
from kcl_write import build_kcl, build_pa  # noqa: E402
from rarc_write import make_rarc  # noqa: E402
from stage_edit import Archive, StageEdit, jmap_hash, yaz0_compress  # noqa: E402

BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
GALAXY = "GuglisPlanetGalaxy"
PLANET = "GuglisPlanetSphere"
MOD = "GuglisPlanet"
STAGE_TEMPLATE = "SnowCapsuleGalaxy"  # one planet, point gravity, aurora sky, Launch Star arrival
SCENARIO_TEMPLATE = "BeltConveyerExGalaxy"  # one scenario, one zone
MODEL_TEMPLATE = "StardustHillPlanet"  # CutStone_v 0, Green_v 1, Ground_v 2
MATERIALS = {"CutStone_v": 0, "Green_v": 1, "Ground_v": 2}
# Texture repeats per 1000 units, as on the template, and the footsteps for the collision.
DENSITY = {"CutStone_v": 0.95, "Green_v": 3.9, "Ground_v": 2.9}
SOUND = {"CutStone_v": "Stone", "Green_v": "Lawn", "Ground_v": "Soil"}
CENTRE = np.array([3070.0, 6070.0, 6470.0])  # Snow Cap's planet centre: its gravity, rail and cameras stay
MINI_RADIUS = 2300.0  # dome miniatures are about this big
SPIN_HITS = 3
SWITCH_BOXES, SWITCH_STAR = 10, 20
STAR_CAMERA = 1  # the star's CameraSetId

MOD_TXT = f"""name=Guglis Testplanet
description=Ein eigener Planet aus Blender: Anflug mit Kamerafahrt, drei Drehkisten, ein lila Stern
priority=1
{GALAXY}.sound=EggStarGalaxy
"""

MESSAGES = f"""# Texts of the planet galaxy (native/CUSTOM_GALAXY.md): ID = text.
GalaxyName_{GALAXY} = Guglis Testplanet
GalaxyNameShort_{GALAXY} = Guglis Testplanet
ScenarioName_{GALAXY}1 = Der lila Stern
"""


def blender_to_game(points):
    """Blender metres, Z up -> game units, Y up, around the planet centre."""
    points = np.asarray(points, dtype=np.float64)
    return np.stack([points[..., 0], points[..., 2], -points[..., 1]], axis=-1) * 100.0


def blender_dir_to_game(vectors):
    vectors = np.asarray(vectors, dtype=np.float64)
    return np.stack([vectors[..., 0], vectors[..., 2], -vectors[..., 1]], axis=-1)


def box_uvs(positions, normals, density):
    """Box mapping at the texture's density: per triangle, the two axes across its normal."""
    uvs = np.zeros((len(positions), 2))
    for tri in range(0, len(positions), 3):
        normal = np.abs(normals[tri:tri + 3].sum(axis=0))
        axis = int(np.argmax(normal))
        across = [a for a in range(3) if a != axis]
        uvs[tri:tri + 3] = positions[tri:tri + 3][:, across] * density / 1000.0
    return uvs


def planet_parts(data, scale=1.0):
    """j3d_mesh parts (one per material) and the collision triangles, centred on the origin."""
    positions = blender_to_game(data["positions"]) * scale
    normals = blender_dir_to_game(data["normals"])
    shades = np.clip(np.asarray(data["shades"]) * 255.0, 0, 255)
    names = [str(n) for n in data["material_names"]]
    tri_material = data["material"]
    parts = []
    for index, name in enumerate(names):
        tris = np.where(tri_material == index)[0]
        if len(tris) == 0:
            continue
        corners = (tris[:, None] * 3 + np.arange(3)[None, :]).reshape(-1)
        p, n = positions[corners], normals[corners]
        colors = np.concatenate([shades[corners], np.full((len(corners), 1), 255.0)], axis=1).astype(np.uint8)
        parts.append(Part(MATERIALS[name], p, n, box_uvs(p, n, DENSITY[name]), np.arange(len(corners)).reshape(-1, 3), colors=colors))
    return parts, positions, names, tri_material


def collision(positions, names, tri_material):
    rows = [{"sound": SOUND[name]} for name in names]
    triangles = np.arange(len(positions)).reshape(-1, 3)
    return build_kcl(positions, triangles, tri_material), build_pa(rows)


def object_archive(folder, files):
    return yaz0_compress(make_rarc(folder.lower(), {name.lower(): data for name, data in files.items()}))


def find_value(table, field, value):
    rows = [row for row in range(len(table.rows)) if table.get(row, field) == value]
    if len(rows) != 1:
        raise ValueError(f"{field}={value}: {len(rows)} rows")
    return rows[0]


def table_rows(table, name):
    return [row for row in range(len(table.rows)) if table.get(row, "name") == name]


def set_pos(table, row, position):
    for axis, value in zip("xyz", position):
        table.set(row, f"pos_{axis}", float(value))


def stand_up(table, row, offset):
    """Turns a placement so that its up points away from the planet centre (the game's rotation
    order: x, then y, then z, in degrees)."""
    up = offset / np.linalg.norm(offset)
    table.set(row, "dir_x", math.degrees(math.asin(up[2])))
    table.set(row, "dir_y", 0.0)
    table.set(row, "dir_z", math.degrees(math.atan2(-up[0], up[1])))


def star_camera(cameras, markers):
    """The star's appear camera (e:パワースター固有NNN, NNN its CameraSetId, as on the disc): fixed
    beyond the star's landing place, looking back at it and at where it comes out. It reuses the camera of Snow
    Cap's Sling Star, which is gone."""
    row = find_value(cameras, "id", "e:スピンドライバ:000:00番目")
    cameras.set(row, "id", f"e:パワースター固有{STAR_CAMERA:03d}")
    cameras.set(row, "camtype", "CAM_TYPE_POINT_FIX")
    watch = (markers["StarAppear"] + markers["Star"]) / 2
    up = watch / np.linalg.norm(watch)
    side = markers["Star"] - markers["StarAppear"]
    side -= up * side.dot(up)
    side /= np.linalg.norm(side)
    offset = 2400.0 * (0.55 * up + 0.83 * side)  # above the star's landing place, outside the planet
    for axis, value in zip("XYZ", watch + CENTRE):
        cameras.set(row, f"wpoint.{axis}", float(value))
    for axis, value in zip("XYZ", up):
        cameras.set(row, f"up.{axis}", float(value))
    cameras.set(row, "dist", float(np.linalg.norm(offset)))
    cameras.set(row, "axis.X", math.asin(offset[1] / np.linalg.norm(offset)))  # elevation
    cameras.set(row, "axis.Y", math.atan2(offset[0], offset[2]))  # direction round the y axis
    cameras.set(row, "camint", 60)


def build_stage(disc, markers, canm):
    stage = StageEdit((disc / f"StageData/{STAGE_TEMPLATE}.arc").read_bytes())
    objects = stage.table("jmp/placement/common/objinfo")
    # Snow Cap's own objects go; its sky, Launch Star arrival and planet stay.
    for name in ("SpinDriver", "TreasureBoxEmpty", "JetTurtle", "Coin"):
        for row in reversed(table_rows(objects, name)):
            del objects.rows[row]
    for path in ("jmp/placement/common/stageobjinfo", "jmp/placement/common/areaobjinfo"):
        stage.table(path).rows.clear()  # its second zone and the view group area
    # Snow Cap's camera sphere (camera c:0000) becomes the game's small-planet camera, which follows
    # Mario round the planet, with the values most of the game's planets use; it covers the planet.
    cubes = stage.table("jmp/placement/common/cameracubeinfo")
    set_pos(cubes, 0, CENTRE)
    for axis in "xyz":
        cubes.set(0, f"scale_{axis}", 10.0)
    cameras = stage.table("camera/cameraparam.bcam")
    row = find_value(cameras, "id", "c:0000")
    cameras.set(row, "camtype", "CAM_TYPE_WONDER_PLANET")
    cameras.set(row, "axis.X", 1500.0)  # nearest and farthest distance from Mario
    cameras.set(row, "axis.Y", 2000.0)
    cameras.set(row, "angleA", 0.79)  # at least this far above the ground (radians)
    planet = table_rows(objects, "LavaTransparentPlanet")[0]
    objects.set(planet, "name", PLANET)
    objects.set(planet, "ViewGroupId", -1)
    set_pos(objects, planet, CENTRE)

    start = markers["MarioStart"] + CENTRE
    starts = stage.table("jmp/start/common/startinfo")
    set_pos(starts, 0, start)
    # The Launch Star rail (path 0) ends above the start: move it whole, keeping its curve.
    points = stage.table("jmp/path/commonpathpointinfo.0")
    last = len(points.rows) - 1
    end = np.array([points.get(last, f"pnt0_{a}") for a in "xyz"])
    delta = start + np.array([0.0, 700.0, 150.0]) - end
    for row in range(len(points.rows)):
        for p in ("pnt0", "pnt1", "pnt2"):
            for axis, d in zip("xyz", delta):
                points.set(row, f"{p}_{axis}", float(points.get(row, f"{p}_{axis}") + d))

    # The challenge: three spin boxes; once all have burst, switch 20 brings the star out: it comes out
    # at GuglisStarAppear and flies to its own place.
    for index in range(3):
        box = stage.new("jmp/placement/common/objinfo", "GuglisSpinBox", *(markers[f"SpinBox{index + 1}"] + CENTRE))
        objects.set(box, "Obj_arg0", SPIN_HITS)
        objects.set(box, "SW_DEAD", SWITCH_BOXES + index)
        stand_up(objects, box, markers[f"SpinBox{index + 1}"])
    watcher = stage.new("jmp/placement/common/objinfo", "GroupSwitchWatcher", *CENTRE)
    objects.set(watcher, "Obj_arg0", 3)
    objects.set(watcher, "SW_B", SWITCH_BOXES)
    objects.set(watcher, "SW_A", SWITCH_STAR)
    appear = stage.new("jmp/placement/common/objinfo", "GuglisStarAppear", *(markers["StarAppear"] + CENTRE))
    objects.set(appear, "SW_A", SWITCH_STAR)
    star = stage.new("jmp/placement/common/objinfo", "PowerStar", *(markers["Star"] + CENTRE))
    objects.set(star, "Obj_arg0", 1)
    objects.set(star, "CameraSetId", STAR_CAMERA)
    stand_up(objects, star, markers["Star"])
    star_camera(stage.table("camera/cameraparam.bcam"), markers)

    stage.archive.contents[stage.archive.find("camera/startscenario1.canm")] = canm
    return stage.build(True)


def build_scenario(disc):
    scenario = StageEdit((disc / f"StageData/{SCENARIO_TEMPLATE}/{SCENARIO_TEMPLATE}Scenario.arc").read_bytes())
    table = scenario.table("scenariodata.bcsv")
    table.header = bytearray(table.header)
    for index, field in enumerate(table.fields):
        if field[0] == jmap_hash(SCENARIO_TEMPLATE):
            struct.pack_into(">I", table.header, 16 + index * 12, jmap_hash(GALAXY))
    table.set(0, "AppearPowerStarObj", "GuglisStarAppear")
    scenario.table("zonelist.bcsv").set(0, "ZoneName", GALAXY)
    return scenario.build(True)


def opening_camera(start):
    sys.path.insert(0, str(HERE))
    from canm import orbit  # noqa: E402

    return orbit(center=tuple(CENTRE), radius=5200.0, height=1200.0, mario=tuple(start))


def other_mod_galaxies(disc, mods):
    """Galaxies other mods in the user directory add with a miniature (a scenario archive and a
    Mini<Galaxy>.arc not on the disc)."""
    found = []
    for scenario in sorted(mods.glob("*/files/StageData/*/*Scenario.arc")):
        galaxy = scenario.parent.name
        folder = scenario.parents[3]
        if folder.name in (MOD, f".{MOD}.building") or galaxy == GALAXY or galaxy in found:
            continue
        if (folder / f"files/ObjectData/Mini{galaxy}.arc").exists() and not (disc / f"StageData/{galaxy}").exists():
            found.append(galaxy)
    return found


def build(disc: Path, mod: Path, planet_dir: Path, from_blend: bool):
    args = [str(BLENDER), "--background", "--python", str(HERE / "planet_blender.py"), "--", str(planet_dir)]
    if from_blend:
        args.append("--from-blend")
    subprocess.run(args, check=True, capture_output=True)
    data = np.load(planet_dir / "GuglisTestPlanet.npz")
    markers = {str(n): blender_to_game(p) for n, p in zip(data["marker_names"], data["marker_positions"])}

    template = Archive((disc / f"ObjectData/{MODEL_TEMPLATE}.arc").read_bytes())
    template_bdl = template.contents[template.find(f"{MODEL_TEMPLATE.lower()}.bdl")]
    collision_version = template.contents[template.find("collisionversion")]

    files = mod / "files"
    (files / "ObjectData").mkdir(parents=True)
    (files / "StageData" / GALAXY).mkdir(parents=True)

    parts, positions, names, tri_material = planet_parts(data)
    model = build_model(template_bdl, parts, name=PLANET.lower())
    kcl, pa = collision(positions, names, tri_material)
    (files / f"ObjectData/{PLANET}.arc").write_bytes(object_archive(PLANET, {
        f"{PLANET}.bdl": model, f"{PLANET}.kcl": kcl, f"{PLANET}.pa": pa, "collisionversion": collision_version}))

    radius = float(np.linalg.norm(positions, axis=1).max())
    mini_parts, _, _, _ = planet_parts(data, scale=MINI_RADIUS / radius)
    mini = f"Mini{GALAXY}"
    (files / f"ObjectData/{mini}.arc").write_bytes(object_archive(mini, {f"{mini}.bdl": build_model(template_bdl, mini_parts, name=mini.lower())}))

    start = markers["MarioStart"] + CENTRE
    (files / f"StageData/{GALAXY}.arc").write_bytes(build_stage(disc, markers, opening_camera(start)))
    (files / f"StageData/{GALAXY}/{GALAXY}Scenario.arc").write_bytes(build_scenario(disc))

    sys.path.insert(0, str(HERE))
    from purple_star import purple_power_star, purple_star_counter  # noqa: E402

    (files / "ObjectData/PowerStar.arc").write_bytes(purple_power_star((disc / "ObjectData/PowerStar.arc").read_bytes()))
    (files / "LayoutData").mkdir()
    (files / "LayoutData/PurpleStars.arc").write_bytes(purple_star_counter((disc / "LayoutData/StarCounter.arc").read_bytes()))

    # Dome 1 (the Terrace) gets the miniature. AstroDome.arc is one file, and only one mod's copy is
    # used (the highest priority's): this one holds the miniatures of the other mods' galaxies too.
    dome = StageEdit((disc / "StageData/AstroDome.arc").read_bytes())
    domes = "jmp/placement/layera/objinfo"
    for galaxy in [GALAXY] + other_mod_galaxies(disc, mod.parent):
        row = dome.add(domes, "MiniEggStarGalaxy@0", -3800.0, 175.0, -1450.0)  # the port sets the orbit
        dome.table(domes).set(row, "name", f"Mini{galaxy}")
    (files / "StageData/AstroDome.arc").write_bytes(dome.build(True))

    (mod / "mod.txt").write_text(MOD_TXT, encoding="utf-8")
    (mod / "messages.txt").write_text(MESSAGES, encoding="utf-8")
    return radius


def main() -> int:
    home = Path.home() / "Library/Application Support/Petari"
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--disc", type=Path, default=home / "Disc/RMGE01")
    parser.add_argument("--user", type=Path, default=home)
    parser.add_argument("--blend-out", type=Path, help="where the .blend and its export go (default <user>/ModSources/GuglisPlanet)")
    parser.add_argument("--from-blend", action="store_true", help="export the edited .blend in --blend-out")
    args = parser.parse_args()
    blend_dir = args.blend_out or args.user / "ModSources" / MOD
    disc = args.disc / "files" if (args.disc / "files").is_dir() else args.disc
    mod = args.user / "mods" / MOD
    work = mod.with_name(f".{MOD}.building")
    shutil.rmtree(work, ignore_errors=True)
    try:
        radius = build(disc, work, blend_dir, args.from_blend)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        shutil.rmtree(work, ignore_errors=True)
        print(f"GuglisPlanet build: {error}", file=sys.stderr)
        return 1
    shutil.rmtree(mod, ignore_errors=True)
    work.replace(mod)
    print(f"Built {mod} (planet radius {radius:.0f} units); the planet in Blender: {blend_dir / 'GuglisTestPlanet.blend'}.")
    print("Turn it on in F1 -> Mods -> Mod folder and restart the game.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

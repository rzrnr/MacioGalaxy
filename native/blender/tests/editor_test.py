"""The editor in Blender, headless, on a throwaway user folder (the disc linked, the mods copied).

    /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
        --python native/blender/tests/editor_test.py -- WORK_DIR [GALAXY]

Opens the galaxy, saves without a change (nothing may be written: transforms read back exactly),
then moves, adds, duplicates and deletes objects, adds gravity and a path, changes a field and a
zone's placement, saves into the mod "EditorTest", and reads the archives back to check each edit.
Prints EDITOR TEST PASS or the first failure and exits non-zero.
"""
import shutil
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
import macio_galaxy_editor as editor  # noqa: E402
from macio_galaxy_editor.convert import to_blender  # noqa: E402
from macio_galaxy_editor.galaxy import USER, GameData  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
work = Path(args[0]).resolve()
galaxy_name = args[1] if len(args) > 1 else "EggStarGalaxy"


def fail(message):
    print(f"EDITOR TEST FAIL: {message}")
    sys.exit(1)


def check(condition, message):
    if not condition:
        fail(message)
    print(f"ok: {message}")


# A user folder of our own: the disc linked, the mods and mods.txt copied.
user = work / "user"
if user.exists():
    shutil.rmtree(user)
(user / "Disc").mkdir(parents=True)
(user / "Disc/RMGE01").symlink_to(USER / "Disc/RMGE01")
if (USER / "mods").is_dir():
    shutil.copytree(USER / "mods", user / "mods")
if (USER / "mods.txt").exists():
    shutil.copy(USER / "mods.txt", user / "mods.txt")

editor.register()
scene = bpy.context.scene
scene.mge_user = str(user)
scene.mge_galaxy = galaxy_name
scene.mge_mod = "EditorTest"


class Reporter:
    def report(self, kind, message):
        print("report", kind, message)


assert bpy.ops.mge.open_galaxy() == {"FINISHED"}
root = bpy.data.collections[f"SMG {galaxy_name}"]
objects = list(root.all_objects)
check(len(objects) > 50, f"{len(objects)} objects in the scene")

# 1. A save without a change writes nothing.
out = editor.export_mod(Reporter(), bpy.context)
check(out == {}, f"no change, nothing written ({sorted(out) if out else ''})")

main = galaxy_name
placed = [o for o in objects if o.get("smg_kind") == "objinfo" and o.get("smg_zone") == main]
moving, removing, changing = placed[0], placed[1], placed[2]
moving_row, moving_table = moving["smg_row"], moving["smg_table"]
removing_key = (removing["smg_table"], removing["smg_row"])
removing_id = removing["smg.l_id"]
changing_key = (changing["smg_table"], changing["smg_row"])
start = moving.location.copy()

# 2. Edits: move (200 game units along game x), delete, change a field, duplicate, add things.
moving.location.x += 2.0
bpy.data.objects.remove(removing, do_unlink=True)
changing["smg.Obj_arg7"] = 77
twin = moving.copy()
twin.data = moving.data
moving.users_collection[0].objects.link(twin)
scene.cursor.location = to_blender((1234.0, 567.0, -890.0))
bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[root.name].children[main] \
    .children[f"{main} common"]
editor.MGE_OT_add.execute(type("Op", (), {"item": "Coin", "report": Reporter.report, "kind": "OBJECT"})(), bpy.context)
editor.MGE_OT_add.execute(type("Op", (), {"item": "GlobalPointGravity", "report": Reporter.report, "kind": "GRAVITY"})(),
                          bpy.context)
gravity = bpy.context.active_object
gravity["smg.Range"] = 2500.0
bpy.context.view_layer.update()
editor.scene_io.refresh_gravity(gravity)
check(max(v.co.length for v in gravity.data.vertices) > 24.0, "gravity range drawn at 2500 units (25 m)")
assert bpy.ops.mge.add_path() == {"FINISHED"}
new_path = bpy.context.active_object
zones = [o for o in root.all_objects if o.get("smg_kind") == "stageobjinfo"]
zone_moved = zones[0] if zones else None
if zone_moved:
    zone_moved.location.z += 1.0

out = editor.export_mod(Reporter(), bpy.context)
check(out and main in out, f"saved zones: {sorted(out or {})}")
mod_file = user / "mods/EditorTest/files/StageData" / f"{main}.arc"
check(mod_file.exists(), f"{mod_file.name} in mods/EditorTest")
check("Folder.EditorTest=on" in (user / "mods.txt").read_text(), "the mod is switched on in mods.txt")

# 3. Read back what the game will load.
game = GameData(user)
zone = game.open(main).zone(main)
check(zone.origin == "EditorTest", "the galaxy's main zone now comes from the test mod")
rows = {}
for record in zone.records():
    rows.setdefault(record.table, []).append(record)
before = GameData(USER).open(main).zone(main)
was = {k: v for k, v in before.table(moving_table).rows and [(k, v) for k, v in __import__("macio_galaxy_editor.galaxy",
       fromlist=["row_values"]).row_values(before.table(moving_table), moving_row).items()]}
now = [r.values for r in rows[moving_table] if r.values.get("l_id") == was["l_id"] and r.values["name"] == was["name"]]
check(len(now) == 1 and abs(now[0]["pos_x"] - (was["pos_x"] + 200)) < 0.05 and abs(now[0]["pos_y"] - was["pos_y"]) < 0.05,
      f"moved object 200 units along game x ({was['pos_x']:.1f} -> {now[0]['pos_x']:.1f})" if now else "moved object found")
names = [r.values["name"] for r in rows["jmp/placement/common/objinfo"]]
check("Coin" in names, "new Coin written")
coin = [r for r in rows["jmp/placement/common/objinfo"] if r.values["name"] == "Coin" and abs(r.values["pos_x"] - 1234) < 0.5]
check(len(coin) == 1 and abs(coin[0].values["pos_y"] - 567) < 0.5 and abs(coin[0].values["pos_z"] + 890) < 0.5,
      "the Coin at the 3D cursor in game coordinates")
ids = [r.values["l_id"] for t in rows.values() for r in t if "l_id" in r.values and r.kind in ("objinfo", "mappartsinfo")]
check(len(ids) == len(set(ids)), "l_id unique among objects and map parts (the duplicate got its own)")
grav = [r for r in rows.get("jmp/placement/common/planetobjinfo", []) if r.values["name"] == "GlobalPointGravity"
        and abs(r.values["Range"] - 2500) < 0.1]
check(len(grav) == 1, "new GlobalPointGravity with Range 2500")
changed = [r for t in rows.values() for r in t if r.values.get("Obj_arg7") == 77]
check(len(changed) == 1, "the changed Obj_arg7")
check(all(r.values.get("l_id") != removing_id for r in rows[removing_key[0]]), "deleted object gone")
twins = [r for r in rows[moving_table] if r.values["name"] == was["name"] and abs(r.values["pos_x"] - now[0]["pos_x"]) < 0.05]
check(len(twins) == 2, "the duplicate (Shift+D) written as a second row")
paths = zone.paths()
check(any(len(p.points) == 2 and p.values["name"] == "Path" for p in paths), "new path with two points")
check(len({p.values["l_id"] for p in paths}) == len(paths), "path ids unique")

# 4. Saving again changes nothing: the written rows are the new originals.
out = editor.export_mod(Reporter(), bpy.context)
check(out == {}, f"second save without a change writes nothing ({sorted(out) if out else ''})")
print("EDITOR TEST PASS")

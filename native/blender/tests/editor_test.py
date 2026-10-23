"""The editor in Blender, headless, on a throwaway user folder (the disc linked, the mods copied).

    /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
        --python native/blender/tests/editor_test.py -- WORK_DIR [GALAXY]

Opens the galaxy, saves without a change (nothing may be written: transforms read back exactly),
then moves, adds, duplicates and deletes objects, adds gravity and a path, changes a field and a
zone's placement, saves into the mod "EditorTest", and reads the archives back to check each edit.
Then: a duplicated path, a coin line, rows after an undo past a save, one angle typed (the others as
the zone stored them), a field copied to all selected, an object moved to another zone, a point_arg.
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
    .children[f"Gemeinsam · {main}"]
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
from collections import Counter  # noqa: E402

def repeated(zone_rows):
    counts = Counter(r.values["l_id"] for r in zone_rows if r.kind in ("objinfo", "mappartsinfo"))
    return {k for k, n in counts.items() if n > 1}

already = repeated(list(GameData(user / "nothing", disc=USER / "Disc/RMGE01").open(main).zone(main).records())) | \
    repeated(list(before.records()))
check(repeated([r for t in rows.values() for r in t]) <= already,
      "no new l_id shared by two objects or map parts (the duplicate got its own; the disc repeats some)")
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

# 5. A duplicated path gets its own ID; a coin line along the new path; rows from before an undo.
disc_path = next(o for o in root.all_objects if o.get("smg_kind") == "path" and o.get("smg_zone") == main
                 and o.get("smg_row", -1) >= 0)
path_twin = disc_path.copy()
path_twin.data = disc_path.data.copy()
disc_path.users_collection[0].objects.link(path_twin)
for other in bpy.context.selected_objects:
    other.select_set(False)
new_path.select_set(True)
bpy.context.view_layer.objects.active = new_path
assert bpy.ops.mge.path_use(name="RailCoin") == {"FINISHED"}
rail_id = new_path["smg.l_id"]
table = [o for o in root.all_objects if o.get("smg_kind") == "objinfo" and o.get("smg_zone") == main
         and o.get("smg_table") == moving_table and o.get("smg_row", -1) >= 0]
single = [o for o in table if sum(1 for x in table if x["smg.name"] == o["smg.name"]) == 1]  # not the duplicate
first, second = single[0], single[1]
first_pos, second_pos = first.matrix_world.translation.copy(), second.matrix_world.translation.copy()
first["smg_row"], second["smg_row"] = second["smg_row"], first["smg_row"]  # as after an undo past a save
count = len(GameData(user).open(main).zone(main).table(moving_table).rows)
out = editor.export_mod(Reporter(), bpy.context)
zone = GameData(user).open(main).zone(main)
paths = zone.paths()
check(len({p.values["l_id"] for p in paths}) == len(paths) and
      sum(1 for p in paths if len(p.points) == len(disc_path.data.splines[0].bezier_points)
          and p.values["name"] == disc_path["smg.name"]) >= 2, "the duplicated path written with its own ID")
rows = [r.values for r in zone.records() if r.table == "jmp/placement/common/objinfo"]
rail = [v for v in rows if v["name"] == "RailCoin" and v.get("CommonPath_ID") == rail_id]
check(len(rail) == 1 and rail[0]["Obj_arg0"] >= 2, f"coin line on path {rail_id} ({rail[0]['Obj_arg0'] if rail else 0} coins)")
values = [r.values for r in zone.records() if r.table == moving_table]
check(len([v for v in values if v["name"] != "RailCoin"]) == count, f"stale rows: {moving_table} keeps its {count} rows")
for obj, pos in ((first, first_pos), (second, second_pos)):
    game = editor.scene_io.to_game(editor.scene_io._zone_local(obj).translation)
    hits = [v for v in values if v["name"] == obj["smg.name"] and abs(v["pos_x"] - game.x) < 0.5 and abs(v["pos_z"] - game.z) < 0.5]
    check(len(hits) == 1, f"stale rows: {obj['smg.name']} written at its own place")

# 6. The stored dir values, a field for all selected, another zone, a path point's point_arg.
scene_io = editor.scene_io
main_objects = [o for o in root.all_objects if o.get("smg_kind") == "objinfo" and o.get("smg_zone") == main
                and o.get("smg_row", -1) >= 0 and o.parent is None]
turned = next(o for o in main_objects if scene_io.stored_dir(o) and
              max(abs(a - b) for a, b in zip(scene_io.stored_dir(o), editor.convert.game_from_basis(scene_io._zone_local(o))[1])) > 1)
dir_before = scene_io.stored_dir(turned)
check(list(turned.mge_game_rot) == [round(a, 2) for a in dir_before] or
      max(abs(a - b) for a, b in zip(turned.mge_game_rot, dir_before)) < 1e-3, f"stored angles shown ({dir_before})")
turned.mge_game_rot = (dir_before[0], dir_before[1], dir_before[2] + 10.0)
turned_id = turned["smg.l_id"]
nudged = next(o for o in main_objects if o is not turned and scene_io.stored_dir(o) and any(scene_io.stored_dir(o)))
nudged_dir = scene_io.stored_dir(nudged)
nudged.location.z += 0.5
nudged_id = nudged["smg.l_id"]

same = [o for o in main_objects if o is not turned and o is not nudged and "smg.Obj_arg0" in o and o.visible_get()]
by_name = {}
for o in same:
    by_name.setdefault(o["smg.name"], []).append(o)
group = next(g for g in by_name.values() if len(g) >= 2)
for o in bpy.context.selected_objects:
    o.select_set(False)
for o in group:
    o.select_set(True)
bpy.context.view_layer.objects.active = group[0]
group[0]["smg.Obj_arg0"] = 4321
assert bpy.ops.mge.copy_field(field="Obj_arg0") == {"FINISHED"}
check(all(o["smg.Obj_arg0"] == 4321 for o in group), f"Obj_arg0 copied to all {len(group)} selected {group[0]['smg.name']}")

other_zone = next(z.name for z in scene.mge_zones if z.name != main)
mover = next(o for o in main_objects if o not in group and o is not turned and o is not nudged)
mover_world = mover.matrix_world.copy()
for o in bpy.context.selected_objects:
    o.select_set(False)
mover.select_set(True)
bpy.context.view_layer.objects.active = mover
assert bpy.ops.mge.move_zone(zone=other_zone) == {"FINISHED"}
check(mover["smg_zone"] == other_zone and (mover.matrix_world.translation - mover_world.translation).length < 1e-4,
      f"{mover['smg.name']} moved to {other_zone}, in the same place")
mover_local = scene_io.to_game(scene_io._zone_local(mover).translation)
mover_name, mover_id = mover["smg.name"], mover["smg.l_id"]

for o in bpy.context.selected_objects:
    o.select_set(False)
new_path.select_set(True)
bpy.context.view_layer.objects.active = new_path
scene.mge_point = 2
scene.mge_point_args = (5, -1, 7, -1, -1, -1, -1, -1)
check(list(scene.mge_point_args)[:3] == [5, -1, 7], "point_arg of point 2 set")
path_id = new_path["smg.l_id"]

out = editor.export_mod(Reporter(), bpy.context)
data = GameData(user).open(main)
zone = data.zone(main)
values = [r.values for r in zone.records()]
row = next(v for v in values if v.get("l_id") == turned_id and v["name"] == turned["smg.name"])
check(abs(row["dir_x"] - dir_before[0]) < 1e-3 and abs(row["dir_y"] - dir_before[1]) < 1e-3 and
      abs(row["dir_z"] - dir_before[2] - 10) < 1e-3, f"one angle changed, the others as stored ({row['dir_x']}, {row['dir_y']}, {row['dir_z']})")
row = next(v for v in values if v.get("l_id") == nudged_id and v["name"] == nudged["smg.name"])
check(all(abs(row[f"dir_{a}"] - d) < 1e-3 for a, d in zip("xyz", nudged_dir)), "a moved object keeps its stored angles")
moved_rows = [r.values for r in data.zone(other_zone).records() if r.values["name"] == mover_name
              and abs(r.values["pos_x"] - mover_local.x) < 0.5 and abs(r.values["pos_z"] - mover_local.z) < 0.5]
check(len(moved_rows) == 1, f"{mover_name} written in {other_zone}")
check(not any(v["name"] == mover_name and v.get("l_id") == mover_id for v in values), f"{mover_name} gone from {main}")
point = next(p for p in zone.paths() if p.values.get("l_id") == path_id).points[1].values
check(point["point_arg0"] == 5 and point["point_arg2"] == 7, "point_arg written for point 2")
print("EDITOR TEST PASS")

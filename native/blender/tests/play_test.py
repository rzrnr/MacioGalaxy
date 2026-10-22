"""An edit made in the editor, played headless in the game (the editor's own preview).

    /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
        --python native/blender/tests/play_test.py -- WORK_DIR [GALAXY]

On a throwaway user folder (as editor_test.py): opens the galaxy, puts a row of five coins and a
spin-able box in front of Mario's start, raises the start's own zone a little nowhere else, saves into
the mod "PlayTest", and runs the preview (refused while the player's game runs). Prints the run's
summary and its pictures, then PLAY TEST PASS when the stage loaded and Mario walked.
"""
import shutil
import sys
import time
from pathlib import Path

import bpy
from mathutils import Matrix

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
import macio_galaxy_editor as editor  # noqa: E402
from macio_galaxy_editor import game as game_io  # noqa: E402
from macio_galaxy_editor.convert import to_blender, to_game  # noqa: E402
from macio_galaxy_editor.galaxy import USER  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
work = Path(args[0]).resolve()
galaxy_name = args[1] if len(args) > 1 else "EggStarGalaxy"

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
scene.mge_user, scene.mge_galaxy, scene.mge_mod = str(user), galaxy_name, "PlayTest"
assert bpy.ops.mge.open_galaxy() == {"FINISHED"}
bpy.context.view_layer.update()
root = bpy.data.collections[f"SMG {galaxy_name}"]
start = next(o for o in root.all_objects if o.get("smg_kind") == "startinfo" and o.get("smg.MarioNo") == 0
             and o.get("smg_zone") == galaxy_name)
front = start.matrix_world.to_3x3() @ to_blender((0, 0, 1)).normalized()
bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[root.name] \
    .children[galaxy_name].children[f"{galaxy_name} common"]


class Op:
    def __init__(self, item):
        self.item, self.kind = item, "ALL"

    def report(self, kind, message):
        print("report", kind, message)


for i in range(5):
    scene.cursor.matrix = Matrix.Translation(start.matrix_world.translation + front * (3.0 + 1.5 * i) + to_blender((0, 80, 0)))
    editor.MGE_OT_add.execute(Op("Coin"), bpy.context)
scene.cursor.matrix = Matrix.Translation(start.matrix_world.translation + front * 4.0 + to_blender((250, 0, 0)))
editor.MGE_OT_add.execute(Op("PunchBox"), bpy.context)

if game_io.game_running():
    print("PLAY TEST SKIP: the player's game is running")
    sys.exit(2)
scene.mge_warp = True
scene.cursor.matrix = Matrix.Translation(start.matrix_world.translation + to_blender((0, 50, 0)))
out = editor.export_mod(Op(""), bpy.context)
print("saved", sorted(out or {}))
preview = game_io.Preview(editor.game_data(scene), galaxy_name, int(scene.mge_scenario), tuple(to_game(scene.cursor.location)))
while (result := preview.poll()) is None:
    time.sleep(2)
passed, summary, pictures = result
for line in summary:
    print(line)
for picture in pictures:
    print("PICTURE", picture)
print("PLAY TEST PASS" if passed else "PLAY TEST FAIL")
sys.exit(0 if passed else 1)

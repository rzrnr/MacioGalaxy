"""Testspielen end to end: an edit played in the level testbed, then a second edit reloaded in-process.

    /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
        --python native/blender/tests/testbed_test.py -- WORK_DIR [GALAXY]

On a throwaway user folder (as editor_test.py): opens the galaxy, puts a row of coins in front of
Mario's start, saves into the mod "TestbedTest" and starts the testbed hidden (--background; refused
while the player's game runs). Once Mario can be played, puts a Goomba beside the start, saves and asks
the running testbed to reload: the Goomba must then be in the game, in the same process. Last, a
reload with a spawn point (the Vorschau-Start). Prints the times the testbed measured and TESTBED TEST
PASS, or the first failure.
"""
import os
import re
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
# Unix sockets take at most 103 bytes of path: beside the editor's own, not in WORK_DIR.
control = game_io.TESTBED / "test.sock"


def fail(message):
    game_io.testbed_command("quit", control=control)
    print(f"TESTBED TEST FAIL: {message}")
    sys.exit(1)


def check(condition, message):
    if not condition:
        fail(message)
    print(f"ok: {message}")


if game_io.game_running():
    print("TESTBED TEST SKIP: the player's game is running")
    sys.exit(2)

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
scene.mge_user, scene.mge_galaxy, scene.mge_mod = str(user), galaxy_name, "TestbedTest"
assert bpy.ops.mge.open_galaxy() == {"FINISHED"}
bpy.context.view_layer.update()
root = bpy.data.collections[f"SMG {galaxy_name}"]
# Mission 1's own start: the editor shows only the layers the mission uses.
starts = [o for o in root.all_objects if o.get("smg_kind") == "startinfo" and o.get("smg.MarioNo") == 0
          and o.get("smg_zone") == galaxy_name and o.visible_get()]
check(starts, f"mission 1's start: {', '.join(o.name for o in starts)}")
start = starts[0]
front = start.matrix_world.to_3x3() @ to_blender((0, 0, 1)).normalized()
bpy.context.view_layer.active_layer_collection = bpy.context.view_layer.layer_collection.children[root.name] \
    .children[galaxy_name].children[f"Gemeinsam · {galaxy_name}"]


class Op:
    def __init__(self, item=""):
        self.item, self.kind = item, "ALL"

    def report(self, kind, message):
        print("report", kind, message)


for i in range(5):
    scene.cursor.matrix = Matrix.Translation(start.matrix_world.translation + front * (3.0 + 1.5 * i) + to_blender((0, 80, 0)))
    editor.MGE_OT_add.execute(Op("Coin"), bpy.context)
check(editor.export_mod(Op(), bpy.context), "coins saved into the mod")

os.environ.setdefault("PETARI_CACHE_DIR", str(game_io.CACHE / "preview/pipeline-cache"))
os.environ.setdefault("SDL_AUDIO_DRIVER", "dummy")
os.environ["PETARI_OBSERVE"] = "1"  # the actors command
game = editor.game_data(scene)
log = game_io.TESTBED / "testbed.log"


def run(testplay, what):
    while (result := testplay.poll(timeout=240)) is None:
        time.sleep(0.25)
    ok, seconds, message = result
    check(ok, f"{what}: {message}" + (f", playable after {seconds:.2f} s" if ok else ""))
    return seconds


def mario_at():
    """Where Mario was when the testbed last gave control (its log)."""
    found = re.findall(r"control [0-9.]+ s after [^,]+, Mario at \((-?\d+), (-?\d+), (-?\d+)\)",
                       log.read_text(errors="replace"))
    return tuple(int(v) for v in found[-1]) if found else None


def goombas_near(point, radius):
    """Goombas the game reports (the testbed's actors command) within radius of point."""
    time.sleep(1.0)  # the list is refreshed twice a second
    reply = game_io.testbed_command("actors", control=control) or ""
    found = []
    for item in reply[3:].split("; "):
        kind, _, where = item.partition(" ")
        if kind == "Goomba":
            at = tuple(float(v) for v in where.split(","))
            if sum((a - b) ** 2 for a, b in zip(at, point)) ** 0.5 < radius:
                found.append(at)
    return found


testplay = game_io.Testplay(game, galaxy_name, 1, control=control, user=work / "tb-user", background=True)
check(testplay.mode == "launch", "no testbed was running: a new one starts")
launch_seconds = run(testplay, "launch")
check(mario_at() is not None, f"Mario at the mission's start {mario_at()}")

# A Goomba 600 units beside the start; saved, then reloaded in the same process.
side = start.matrix_world.to_3x3() @ to_blender((1, 0, 0)).normalized()
goomba = start.matrix_world.translation + side * 6.0 + to_blender((0, 100, 0))
before = goombas_near(tuple(to_game(goomba)), 400)
scene.cursor.matrix = Matrix.Translation(goomba)
editor.MGE_OT_add.execute(Op("Kuribo"), bpy.context)
check(editor.export_mod(Op(), bpy.context), f"a Goomba saved into the mod ({len(before)} there before)")
pid = testplay.process.pid
testplay = game_io.Testplay(game, galaxy_name, 1, control=control, user=work / "tb-user", background=True)
check(testplay.mode == "reload", "the running testbed reloads")
reload_seconds = run(testplay, "reload")
status = game_io.testbed_status(control)
check(status and int(status["pid"]) == pid, "same process")
after = goombas_near(tuple(to_game(goomba)), 400)
check(len(after) == len(before) + 1, f"after the reload the new Goomba is in the game: {after}")

# The Vorschau-Start: a spawn point 300 units above the moved start.
spawn = tuple(to_game(start.matrix_world.translation))
spawn = (spawn[0], spawn[1] + 300, spawn[2])
testplay = game_io.Testplay(game, galaxy_name, 1, spawn=spawn, control=control, user=work / "tb-user", background=True)
spawn_seconds = run(testplay, "reload with a spawn point")
time.sleep(1.0)
check("spawn at (" in log.read_text(errors="replace"), "Mario put at the spawn point")

game_io.testbed_command("quit", control=control)
print(f"TESTBED TIMES: launch {launch_seconds:.2f} s, reload {reload_seconds:.2f} s, reload with spawn {spawn_seconds:.2f} s")
print("TESTBED TEST PASS")

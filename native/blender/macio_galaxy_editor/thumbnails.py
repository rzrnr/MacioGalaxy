"""Preview pictures of the catalog's objects: their models rendered once, 128 x 128, transparent.

The editor starts this file in a second Blender, headless and at low priority:

    Blender --background --factory-startup --python thumbnails.py -- LIST.json USER_DIR

LIST.json: [[object name, {fields}], ...]. Each model is rendered with the Workbench (textures,
studio light) from the front, a little from the right and above, framed by its bounding box, into
~/Library/Caches/MacioGalaxyEditor/thumbs/<archive>.png. Objects without a model are skipped. While
the player's game runs the renders wait (a second GPU user has crashed the game before).
The editor loads the pictures as they appear (Thumbnails.refresh).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

CACHE = Path.home() / "Library/Caches/MacioGalaxyEditor"
THUMBS = CACHE / "thumbs"
SIZE = 128


def thumb_path(archive: str) -> Path:
    return THUMBS / f"{archive}.png"


# --- in the editor ---------------------------------------------------------------------------


class Thumbnails:
    """The preview icons (bpy.utils.previews) and the background renderer."""

    def __init__(self):
        import bpy.utils.previews
        self.previews = bpy.utils.previews.new()
        self.process = None

    def icon(self, archive: str) -> int:
        """The icon id of an archive's picture, 0 while there is none."""
        if archive in self.previews:
            return self.previews[archive].icon_id
        path = thumb_path(archive)
        if path.exists():
            return self.previews.load(archive, str(path), "IMAGE").icon_id
        return 0

    def missing(self, items):
        return [(name, values) for name, values, archive in items if not thumb_path(archive).exists()]

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, items, user: Path):
        """Renders the pictures of items ((name, values, archive)) that are missing, in the background."""
        todo = self.missing(items)
        if not todo or self.running():
            return len(todo)
        import bpy
        THUMBS.mkdir(parents=True, exist_ok=True)
        listing = CACHE / "thumbs-todo.json"
        listing.write_text(json.dumps(todo))
        self.process = subprocess.Popen(["nice", "-n", "15", bpy.app.binary_path, "--background", "--factory-startup",
                                         "--python", str(Path(__file__)), "--", str(listing), str(user)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return len(todo)

    def close(self):
        import bpy.utils.previews
        if self.running():
            self.process.terminate()
        bpy.utils.previews.remove(self.previews)


# --- in the background Blender ---------------------------------------------------------------


def _render_all(listing: Path, user: Path):
    import bpy
    import numpy as np
    from mathutils import Vector

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from macio_galaxy_editor.galaxy import GameData
    from macio_galaxy_editor.game import game_running
    from macio_galaxy_editor.models import ModelLibrary, archive_name

    scene = bpy.context.scene
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.light = "STUDIO"
    scene.render.film_transparent = True
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    camera = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    holder = bpy.data.objects.new("model", bpy.data.meshes.new("empty"))
    scene.collection.objects.link(holder)
    library = ModelLibrary(GameData(user))
    view = Vector((0.55, -1.0, 0.45)).normalized()
    for name, values in json.loads(listing.read_text()):
        archive = archive_name(name, values)
        out = thumb_path(archive)
        if out.exists():
            continue
        mesh = library.mesh(name, values)
        if mesh is None or not len(mesh.vertices):
            continue
        while game_running():
            time.sleep(5)
        holder.data = mesh
        # Framed by the bulk of the vertices: a few far ones (a shadow plane, an effect's anchor) would
        # leave the model a speck.
        points = np.empty(len(mesh.vertices) * 3, np.float32)
        mesh.vertices.foreach_get("co", points)
        points = points.reshape(-1, 3)
        low, high = np.percentile(points, 3, axis=0), np.percentile(points, 97, axis=0)
        centre = Vector(((low + high) / 2).tolist())
        radius = float(np.linalg.norm(high - low)) / 2 or 1.0
        camera.data.lens = 50
        camera.data.clip_end = radius * 20
        camera.location = centre + view * radius * 2.4
        camera.rotation_mode = "QUATERNION"
        camera.rotation_quaternion = (centre - camera.location).to_track_quat("-Z", "Y")
        scene.render.filepath = str(out.with_suffix(".tmp.png"))
        bpy.ops.render.render(write_still=True)
        out.with_suffix(".tmp.png").rename(out)  # appears whole, never half written


if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1:]
    _render_all(Path(arguments[0]), Path(arguments[1]))


# --- shapes (areas, cameras, gravity): drawn without Blender -------------------------------


def shape_thumbnails(catalog, force=False):
    """Pictures of the objects that are shapes, not models: their wire shape at an angle, in the kind's
    colour (as in the viewport), drawn with numpy (Blender's Python has no Pillow). Returns how many."""
    import math

    import numpy as np

    from . import shapes
    from .models import write_png
    colours = {"areaobjinfo": (80, 230, 90), "cameracubeinfo": (190, 80, 255), "planetobjinfo": (30, 215, 240)}
    THUMBS.mkdir(parents=True, exist_ok=True)
    big = SIZE * 3
    ys, xs = np.mgrid[-3:4, -3:4]
    brush = (xs ** 2 + ys ** 2) <= 9
    written = 0
    yaw, pitch = math.radians(35), math.radians(25)
    for name in catalog.names():
        entry = catalog.entries[name]
        kind = entry["kind"]
        if kind not in colours:
            continue
        out = thumb_path(name)
        if out.exists() and not force:
            continue
        if kind == "planetobjinfo":
            values = dict(catalog.defaults(name))
            if not values.get("Range") or values["Range"] <= 0 or values["Range"] > 5000:
                values["Range"] = 800.0
            verts, edges, _ = shapes.gravity_shape(name, values, (1.0, 1.0, 1.0))
        else:
            verts, edges, _ = shapes.area_shape(shapes.area_shape_name(name, entry.get("area_shape")))
        if not verts or not edges:
            continue
        v = np.array(verts, dtype=np.float64)
        x1 = v[:, 0] * math.cos(yaw) - v[:, 2] * math.sin(yaw)
        z1 = v[:, 0] * math.sin(yaw) + v[:, 2] * math.cos(yaw)
        y1 = v[:, 1] * math.cos(pitch) - z1 * math.sin(pitch)
        px, py = x1, -y1
        span = max(px.max() - px.min(), py.max() - py.min()) or 1.0
        scale = big * 0.78 / span
        px = (px - (px.max() + px.min()) / 2) * scale + big / 2
        py = (py - (py.max() + py.min()) / 2) * scale + big / 2
        mask = np.zeros((big, big), bool)
        for a, b in edges:
            steps = int(max(abs(px[b] - px[a]), abs(py[b] - py[a]))) + 1
            t = np.linspace(0.0, 1.0, steps)
            lx = np.clip(np.round(px[a] + (px[b] - px[a]) * t).astype(int), 3, big - 4)
            ly = np.clip(np.round(py[a] + (py[b] - py[a]) * t).astype(int), 3, big - 4)
            for dy, dx in zip(*np.nonzero(brush)):
                mask[ly + dy - 3, lx + dx - 3] = True
        alpha = mask.reshape(SIZE, 3, SIZE, 3).mean(axis=(1, 3))  # 3x3 supersampling
        image = np.zeros((SIZE, SIZE, 4), np.uint8)
        image[..., :3] = colours[kind]
        image[..., 3] = (alpha * 255).astype(np.uint8)
        write_png(out, image)
        written += 1
    return written

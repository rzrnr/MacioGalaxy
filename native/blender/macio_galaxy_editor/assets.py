"""The catalog as a Blender asset library: the game's objects in the Asset Browser, dragged into the scene.

- build_library(): in a second, headless Blender (this file run as a script) every catalog object
  becomes an empty marked as an asset: its name in the game, the object database's notes as its
  description, its kind and category as tags, the category as its asset catalog, the model's preview
  picture (thumbnails.py) as its preview, and smg_asset_name = the object's name. The file is
  <library>/MarioGalaxy.blend with blender_assets.cats.txt beside it; the library folder is
  ~/Library/Application Support/MacioGalaxyEditor/AssetLibrary, registered as "Mario Galaxy".
- A dropped asset arrives as such an empty at the spot under the mouse. adopt_dropped() turns it into
  the editor's object (scene_io.new_object, with the model) in the active layer, its up axis along the
  surface it was dropped on.
"""
import json
import subprocess
import sys
import uuid
from pathlib import Path

LIBRARY = Path.home() / "Library/Application Support/MacioGalaxyEditor/AssetLibrary"
LIBRARY_NAME = "Mario Galaxy"
BLEND = LIBRARY / "MarioGalaxy.blend"
NAMES = LIBRARY / "names.json"  # asset name -> object name
NAMESPACE = uuid.UUID("6b1f0a52-6a55-4a5e-9a1e-4d61726961a0")
KIND_CATALOG = {"objinfo": "Objekte", "mappartsinfo": "Map-Teile", "areaobjinfo": "Areas", "cameracubeinfo": "Kameras",
                "planetobjinfo": "Gravity", "startinfo": "Startpunkte", "childobjinfo": "Objekte", "demoobjinfo": "Sonstiges",
                "soundinfo": "Sonstiges", "generalposinfo": "Sonstiges"}


def catalog_path(entry: dict) -> str:
    """The asset catalog of a catalog entry: its kind, then the database's category ("Objekte/Enemies")."""
    kind = KIND_CATALOG.get(entry["kind"], "Sonstiges")
    category = (entry.get("category") or "").replace("/", "-").strip()
    return f"{kind}/{category}" if category and kind in ("Objekte", "Map-Teile") else kind


def catalog_id(path: str) -> str:
    return str(uuid.uuid5(NAMESPACE, path))


def write_catalogs(paths):
    lines = ["# Mario Galaxy objects (MacioGalaxy editor, assets.py)", "VERSION 1", ""]
    seen = set()
    for path in sorted(paths):
        parts = path.split("/")
        for depth in range(1, len(parts) + 1):
            sub = "/".join(parts[:depth])
            if sub not in seen:
                seen.add(sub)
                lines.append(f"{catalog_id(sub)}:{sub}:{sub.replace('/', '-')}")
    (LIBRARY / "blender_assets.cats.txt").write_text("\n".join(lines) + "\n")


# --- in the editor ---------------------------------------------------------------------------


def start_build(catalog, user: Path):
    """Writes the entries and starts the headless build; returns the process."""
    import bpy
    LIBRARY.mkdir(parents=True, exist_ok=True)
    from .models import archive_name
    from .thumbnails import shape_thumbnails
    shape_thumbnails(catalog)  # areas, cameras, gravity: wire pictures (models: thumbnails.py's renders)
    entries = []
    for name in catalog.names():
        entry = catalog.entries[name]
        if entry.get("unused"):
            continue
        entries.append(dict(name=name, label=entry["label"], kind=entry["kind"], category=entry.get("category", ""),
                            notes=entry.get("notes", ""), archive=archive_name(name, catalog.defaults(name)),
                            catalog=catalog_path(entry)))
    listing = LIBRARY / "entries.json"
    listing.write_text(json.dumps(entries))
    write_catalogs({e["catalog"] for e in entries})
    return subprocess.Popen(["nice", "-n", "10", bpy.app.binary_path, "--background", "--factory-startup", "--python",
                             str(Path(__file__)), "--", str(listing)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def register_library(context):
    """The library in the preferences (once); the Asset Browser then lists it."""
    libraries = context.preferences.filepaths.asset_libraries
    for library in libraries:
        if Path(library.path) == LIBRARY:
            return library
    library = libraries.new(name=LIBRARY_NAME, directory=str(LIBRARY))
    library.import_method = "APPEND"
    return library


def adopt_dropped(context, obj, editor):
    """A dropped asset empty -> the editor's object at the same place, in the active layer."""
    import bpy

    from . import scene_io
    name = obj["smg_asset_name"]
    location = obj.matrix_world.translation.copy()
    scene = context.scene
    cat = editor.catalog(scene)
    entry = cat.entries.get(name)
    collection = editor._target_collection(context)
    zone = collection["smg_zone"]
    parent = editor._zone_parent(context, zone)
    normal = surface_normal(context, location, exclude=obj)
    matrix = aligned_matrix(location, normal)
    local = parent.matrix_world.inverted() @ matrix if parent is not None else matrix
    bpy.data.objects.remove(obj, do_unlink=True)
    new = scene_io.new_object(name, entry["kind"] if entry else "objinfo", zone, cat.defaults(name), local, collection, cat,
                              parent=parent, library=editor.model_library(scene))
    for other in context.selected_objects:
        other.select_set(False)
    new.select_set(True)
    context.view_layer.objects.active = new
    return new


def surface_normal(context, location, exclude=None):
    """The surface's normal at location, seen from the viewport (None when nothing is there)."""
    from mathutils import Vector
    view = None
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D" and view is None:
                view = area.spaces[0].region_3d
    origin = view.view_matrix.inverted().translation if view is not None else location + Vector((0, 0, 50))
    direction = (location - origin)
    if direction.length < 1e-6:
        return None
    direction.normalize()
    hidden = exclude is not None and not exclude.hide_get()
    if hidden:
        exclude.hide_set(True)
    hit, _, normal, _, _, _ = context.scene.ray_cast(context.evaluated_depsgraph_get(), location - direction * 0.5, direction,
                                                     distance=1.5)
    if hidden:
        exclude.hide_set(False)
    return normal if hit else None


def aligned_matrix(location, normal):
    """A matrix at location whose up axis (game +Y: Blender +Z) points along normal."""
    from mathutils import Matrix, Vector
    if normal is None:
        return Matrix.Translation(location)
    rotation = Vector((0, 0, 1)).rotation_difference(normal).to_matrix().to_4x4()
    return Matrix.Translation(location) @ rotation


# --- in the headless Blender -----------------------------------------------------------------


def _build(listing: Path):
    import bpy
    import numpy as np
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    thumbs = Path.home() / "Library/Caches/MacioGalaxyEditor/thumbs"
    collection = bpy.context.scene.collection
    for entry in json.loads(listing.read_text()):
        label = entry["label"] if entry["label"] != entry["name"] else entry["name"]
        obj = bpy.data.objects.new(label, None)
        obj.empty_display_size = 0.5
        collection.objects.link(obj)
        obj["smg_asset_name"] = entry["name"]
        obj.asset_mark()
        data = obj.asset_data
        data.description = (entry["notes"] or "")[:900]
        data.catalog_id = catalog_id(entry["catalog"])
        for tag in {entry["name"], entry["kind"], entry["category"]} - {""}:
            data.tags.new(tag)
        picture = thumbs / f"{entry['archive']}.png"
        if picture.exists():
            image = bpy.data.images.load(str(picture))
            preview = obj.preview_ensure()
            preview.image_size = image.size
            pixels = np.empty(image.size[0] * image.size[1] * 4, np.float32)
            image.pixels.foreach_get(pixels)
            preview.image_pixels_float.foreach_set(pixels)
            bpy.data.images.remove(image)
    for image in list(bpy.data.images):
        bpy.data.images.remove(image)
    # The shelf hands back an asset's name: which object it stands for.
    NAMES.write_text(json.dumps({obj.name: obj["smg_asset_name"] for obj in bpy.data.objects if obj.get("smg_asset_name")}))
    tmp = BLEND.with_suffix(".tmp.blend")
    bpy.ops.wm.save_as_mainfile(filepath=str(tmp), compress=True)
    tmp.replace(BLEND)


if __name__ == "__main__":
    _build(Path(sys.argv[sys.argv.index("--") + 1]))

"""MacioGalaxy editor: Super Mario Galaxy levels in Blender (native/blender/README.md).

Opens a galaxy (the disc with the enabled mods on top) as objects, areas, gravity and paths in the
scene, edits them with Blender's own tools, saves the changed zones as a MacioGalaxy mod, and plays
them, headless with pictures or in the game. The interface: ui.py (the 3D view's sidebar, N).
"""
bl_info = {
    "name": "MacioGalaxy Editor",
    "author": "rzrnr",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D View > Sidebar (N) > Galaxie, Objekte, Eigenschaften, Spiel",
    "description": "Edit Super Mario Galaxy levels and play them in MacioGalaxy",
    "category": "Import-Export",
}

import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import bpy  # noqa: E402
from bpy.app.handlers import persistent  # noqa: E402
from bpy.props import BoolProperty, EnumProperty, StringProperty  # noqa: E402

from . import game as game_io  # noqa: E402
from . import scene_io  # noqa: E402
from . import assets  # noqa: E402
from . import hud  # noqa: E402
from . import shelf  # noqa: E402
from . import tools  # noqa: E402
from . import ui  # noqa: E402
from . import workspace  # noqa: E402
from .catalog import KIND_LABEL, Catalog  # noqa: E402
from .models import ModelLibrary  # noqa: E402
from .convert import to_game  # noqa: E402
from .galaxy import USER, GameData, Path_, PathPoint, read_tree  # noqa: E402

_cache = {}
GALAXY_SCENE = "Mario Galaxy"


def game_data(scene) -> GameData:
    user = Path(bpy.path.abspath(scene.mge_user or str(USER)))
    key = ("game", str(user))
    if key not in _cache:
        _cache[key] = GameData(user)
    return _cache[key]


def catalog(scene) -> Catalog:
    key = ("catalog", scene.mge_user)
    if key not in _cache:
        _cache[key] = Catalog(game_data(scene))
    return _cache[key]


def model_library(scene):
    """The game's models for this scene (None while "Modelle" is off)."""
    if not scene.mge_models:
        return None
    key = ("models", scene.mge_user)
    if key not in _cache:
        _cache[key] = ModelLibrary(game_data(scene))
    return _cache[key]


def open_galaxy(scene):
    key = ("galaxy", scene.mge_user, scene.get("smg_galaxy"))
    if key not in _cache:
        _cache[key] = game_data(scene).open(scene["smg_galaxy"])
    return _cache[key]


def forget(scene):
    for key in [k for k in _cache if k[0] in ("game", "galaxy", "names")]:
        del _cache[key]


# --- properties ------------------------------------------------------------------------------


def galaxy_names(scene) -> dict:
    key = ("names", scene.mge_user)
    if key not in _cache:
        _cache[key] = game_data(scene).galaxy_names()
    return _cache[key]


def galaxy_label(scene, name):
    shown = galaxy_names(scene).get(name)
    return f"{shown} ({name})" if shown else name


def _galaxy_search(self, context, edit_text):
    """Galaxies as "<name in the game> (<internal name>)", found by either."""
    scene = context.scene
    text = edit_text.lower()
    labels = [galaxy_label(scene, n) for n in game_data(scene).galaxies()]
    return sorted(label for label in labels if text in label.lower())


def _galaxy_from_field(text: str) -> str:
    text = text.strip()
    return text[text.rindex("(") + 1:-1] if text.endswith(")") and "(" in text else text


def _scenarios(self, context):
    scene = context.scene
    if not scene.get("smg_galaxy"):
        return [("1", "1", "")]
    try:
        galaxy = open_galaxy(scene)
    except (OSError, KeyError):
        return [("1", "1", "")]
    # One list per galaxy, kept: Blender holds on to the strings of the list it was given.
    key = ("scenario_items", scene.mge_user, galaxy.name)
    if key not in _cache:
        names = game_data(scene).messages(f"ScenarioName_{galaxy.name}")

        def label(s):
            layers = " ".join(layer[-1].upper() for layer in s.layers(galaxy.name)[1:])
            shown = names.get(f"ScenarioName_{galaxy.name}{s.no}") or s.name
            return f"{s.no}: {shown}" + (f"   · Ebenen {layers}" if layers else "")
        _cache[key] = [(str(s.no), label(s), f"Szenario {s.no}: {s.name}") for s in galaxy.scenarios]
    return _cache[key]


def _models_changed(self, context):
    scene = context.scene
    root = bpy.data.collections.get(f"SMG {scene.get('smg_galaxy')}")
    if root is not None:
        scene_io.show_models(root, model_library(scene))


def _scenario_changed(self, context):
    scene = context.scene
    if scene.get("smg_galaxy"):
        scene["smg_scenario"] = int(scene.mge_scenario)
        ui.apply_scenario(scene, open_galaxy(scene))


# --- operators -------------------------------------------------------------------------------


class MGE_OT_open(bpy.types.Operator):
    bl_idname = "mge.open_galaxy"
    bl_label = "Galaxie öffnen"
    bl_description = ("Die gewählte Galaxie (Disc und eingeschaltete Mods) öffnen, in einer eigenen Szene \"Mario Galaxy\"; "
                      "eine offene wird ersetzt")
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        if context.scene.get("mge_dirty"):
            return context.window_manager.invoke_confirm(self, event, title="Ungespeicherte Änderungen",
                                                         message="Die offene Galaxie hat ungespeicherte Änderungen. "
                                                                 "Trotzdem eine andere öffnen?",
                                                         confirm_text="Öffnen", icon="WARNING")
        return self.execute(context)

    def execute(self, context):
        scene = _galaxy_scene(context)
        name = _galaxy_from_field(scene.mge_galaxy)
        forget(scene)
        game = game_data(scene)
        if name not in game.galaxies():
            self.report({"ERROR"}, f"Keine Galaxie {name!r}")
            return {"CANCELLED"}
        galaxy = game.open(name)
        _cache[("galaxy", scene.mge_user, name)] = galaxy
        _cache.pop(("models", scene.mge_user), None)  # mods may have changed models since
        count = scene_io.import_galaxy(context, galaxy, galaxy.scenarios[0].no, catalog(scene), model_library(scene))
        scene.mge_scenario = str(galaxy.scenarios[0].no)
        ui.sync_zones(scene, galaxy)
        if not scene.mge_mod:
            origin = scene.get("smg_main_origin")
            scene.mge_mod = origin if origin and origin != "disc" else "BlenderEdits"
        _setup_views(context)
        scene["mge_dirty"] = False
        scene["mge_armed"] = False
        bpy.app.timers.register(lambda: _arm(scene.name), first_interval=1.5)
        if context.window is not None and (context.workspace is None or context.workspace.name != workspace.NAME):
            bpy.ops.mge.workspace()
        self.report({"INFO"}, f"{name}: {count} Objekte und Pfade in {len(galaxy.zone_names)} Zonen")
        return {"FINISHED"}


def _galaxy_scene(context):
    """The scene galaxies open in: "Mario Galaxy", made when the current scene has other things in it
    (the user's own objects stay where they are), and shown in the window."""
    scene = context.scene
    foreign = [o for o in scene.objects if not o.get("smg_kind")]
    if not foreign or context.window is None or bpy.app.background:
        return scene
    target = bpy.data.scenes.get(GALAXY_SCENE)
    if target is None:
        target = bpy.data.scenes.new(GALAXY_SCENE)
        for prop in ("mge_user", "mge_galaxy", "mge_mod", "mge_models"):
            setattr(target, prop, getattr(scene, prop))
    context.window.scene = target
    return target


def _arm(scene_name):
    """From now on, edits count as unsaved (the import's own updates have passed)."""
    scene = bpy.data.scenes.get(scene_name)
    if scene is not None:
        scene["mge_armed"] = True
        scene["mge_count"] = _object_count(scene)
    return None


def _object_count(scene):
    """How many objects the open galaxy has (a deletion changes it; transforms mark the rest)."""
    root = bpy.data.collections.get(f"SMG {scene.get('smg_galaxy')}")
    return len(root.all_objects) if root is not None else 0


def message_text(scene, zone, name, number):
    """The game's text for an NPC's MessageId (<Zone>_<Name><nnn>), or ""."""
    key = ("messages", scene.mge_user, zone)
    if key not in _cache:
        _cache[key] = game_data(scene).messages(f"{zone}_")
    return _cache[key].get(f"{zone}_{name}{number:03d}", "")


def mod_enabled(scene):
    """Whether the target mod is switched on in mods.txt (None while it does not exist yet)."""
    mod = (scene.mge_mod or "").strip()
    match = next((m for m in game_data(scene).mods if m.name == mod), None)
    return None if match is None else match.enabled


class MGE_OT_mod_toggle(bpy.types.Operator):
    bl_idname = "mge.mod_toggle"
    bl_label = "Mod an/aus"
    bl_description = "Den Ziel-Mod in mods.txt ein- oder ausschalten (aus: das Spiel lädt wieder das Original)"

    def execute(self, context):
        scene = context.scene
        on = not mod_enabled(scene)
        game_io.set_mod_enabled(game_data(scene), scene.mge_mod.strip(), on)
        forget(scene)
        self.report({"INFO"}, f"Mod {scene.mge_mod} {'an' if on else 'aus: das Spiel lädt das Original'}")
        return {"FINISHED"}


class MGE_OT_view_start(bpy.types.Operator):
    bl_idname = "mge.view_start"
    bl_label = "Zum Start"
    bl_description = "Die Ansicht auf Marios Startpunkt richten (wenn man sich im Raum verloren hat)"

    def execute(self, context):
        root = bpy.data.collections.get(f"SMG {context.scene.get('smg_galaxy')}")
        start = next((o for o in root.all_objects if o.get("smg_kind") == "startinfo"), None) if root else None
        for area in context.window.screen.areas:
            if area.type == "VIEW_3D":
                view = area.spaces[0].region_3d
                if start is not None:
                    view.view_location = start.matrix_world.translation
                    view.view_distance = 25.0
                    from mathutils import Euler
                    view.view_rotation = Euler((1.1, 0.0, 0.5)).to_quaternion()
                area.tag_redraw()
                return {"FINISHED"}
        return {"CANCELLED"}


def _setup_views(context):
    """Every 3D view sees as far as a galaxy reaches (the look is the Galaxie workspace's: workspace.py)."""
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces[0].clip_end = max(area.spaces[0].clip_end, 20000.0)


def _target_collection(context):
    """The layer collection new things go into: the active one, else the active object's, else main common."""
    layer_coll = context.view_layer.active_layer_collection.collection
    if layer_coll.get("smg_layer") not in (None, "path"):
        return layer_coll
    obj = context.active_object
    if obj is not None:
        for coll in obj.users_collection:
            if coll.get("smg_layer") not in (None, "path"):
                return coll
    galaxy = context.scene["smg_galaxy"]
    root = bpy.data.collections[f"SMG {galaxy}"]
    return scene_io.layer_collection(root, galaxy, "common")


def _zone_parent(context, zone):
    """The empty that places the zone in the galaxy (None for the main zone)."""
    for obj in bpy.data.collections[f"SMG {context.scene['smg_galaxy']}"].all_objects:
        if obj.get("smg_zone") == zone and obj.parent is not None and obj.parent.get("smg_kind") == "stageobjinfo":
            return obj.parent
    return None


def _catalog_items(self, context):
    cat = catalog(context.scene)
    kinds = {"ALL": None, "GRAVITY": "planetobjinfo", "AREA": "areaobjinfo", "CAMERA": "cameracubeinfo",
             "MAPPARTS": "mappartsinfo", "OBJECT": "objinfo", "START": "startinfo"}
    kind = kinds.get(getattr(self, "kind", "ALL"))
    items = []
    for name in cat.names(kind):
        entry = cat.entries[name]
        label = name if entry["label"] == name else f"{name} – {entry['label']}"
        items.append((name, f"{label}  [{KIND_LABEL.get(entry['kind'], entry['kind'])}]", entry["notes"][:200]))
    _cache["catalog_items"] = items
    return items


class MGE_OT_add(bpy.types.Operator):
    bl_idname = "mge.add_object"
    bl_label = "Objekt hinzufügen"
    bl_description = "Ein Objekt des Spiels am 3D-Cursor in die aktive Ebene setzen (Suche nach Name)"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "item"

    kind: EnumProperty(items=[("ALL", "Alle", ""), ("OBJECT", "Objekte", ""), ("MAPPARTS", "Map-Teile", ""),
                              ("GRAVITY", "Gravity", ""), ("AREA", "Areas", ""), ("CAMERA", "Kamera-Areas", ""),
                              ("START", "Startpunkte", "")], default="ALL")
    item: EnumProperty(items=_catalog_items)

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.view_layer.update()  # the zones' world matrices for the cursor
        cat = catalog(context.scene)
        name = self.item
        entry = cat.entries[name]
        coll = _target_collection(context)
        zone = coll["smg_zone"]
        parent = _zone_parent(context, zone)
        cursor = context.scene.cursor.matrix.copy()
        local = parent.matrix_world.inverted() @ cursor if parent is not None else cursor
        values = cat.defaults(name)
        obj = scene_io.new_object(name, entry["kind"], zone, values, local.normalized(), coll, cat, parent=parent,
                                  library=model_library(context.scene))
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        self.report({"INFO"}, f"{name} in {coll.name}")
        return {"FINISHED"}


class MGE_OT_add_path(bpy.types.Operator):
    bl_idname = "mge.add_path"
    bl_label = "Path hinzufügen"
    bl_description = "Einen neuen Path (zwei Punkte) am 3D-Cursor in der Zone der aktiven Ebene anlegen"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def execute(self, context):
        context.view_layer.update()
        zone = _target_collection(context)["smg_zone"]
        parent = _zone_parent(context, zone)
        cursor = context.scene.cursor.location
        local = (parent.matrix_world.inverted() @ cursor) if parent is not None else cursor
        start = to_game(local)
        points = []
        for dx in (0.0, 1000.0):
            p = {f"pnt{i}_{a}": v for i in range(3) for a, v in zip("xyz", (start.x + dx, start.y, start.z))}
            points.append(PathPoint(p))
        values = {"name": "Path", "type": "Bezier", "closed": "OPEN", "l_id": -1, "usage": "General", "Path_ID": -1,
                  **{f"path_arg{i}": -1 for i in range(8)}}
        coll = bpy.data.collections.get(scene_io.paths_collection_name(zone)) or _target_collection(context)
        for point in points:
            point.values.update({f"point_arg{k}": -1 for k in range(8)})
        obj = scene_io.make_path(Path_(zone, -1, values, points), zone, coll, parent)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


def export_mod(operator, context):
    """Writes the changed zones into the target mod; returns the zones written (or None on error)."""
    scene = context.scene
    galaxy = open_galaxy(scene)
    mod = scene.mge_mod.strip() or "BlenderEdits"
    # Only what is in the galaxy's collection is saved: say so for objects moved out of it (M, Outliner).
    root = bpy.data.collections.get(f"SMG {galaxy.name}")
    inside = set(root.all_objects) if root is not None else set()
    outside = [o.name for o in scene.objects if o.get("smg_kind") and o not in inside]
    if outside:
        operator.report({"WARNING"}, f"{len(outside)} Galaxie-Objekte liegen außerhalb von „SMG {galaxy.name}“ und "
                                     f"fehlen im Mod (z. B. {outside[0]}): zurück in eine Ebene legen")
    try:
        edits = scene_io.collect(scene, galaxy)
        out = {}
        for zone_name, (tables, paths) in edits.items():
            zone = galaxy.zone(zone_name)
            had_paths = "jmp/path/commonpathinfo" in zone.tree.files
            data = zone.rebuild(tables, paths if (paths or had_paths) else None)
            if read_tree(data).files != zone.tree.files:
                out[zone_name] = data
    except (ValueError, KeyError, RuntimeError) as error:
        operator.report({"ERROR"}, str(error))
        return None
    scene["mge_dirty"] = False
    scene["mge_count"] = _object_count(scene)
    if out:
        game_io.write_mod(game_data(scene), mod, out)
        forget(scene)
        # The mod now supplies these zones: read them from there from now on, keep the scene.
        _cache[("galaxy", scene.mge_user, galaxy.name)] = game_data(scene).open(galaxy.name)
        scene_io.rebase(edits, out)
    return out


class MGE_OT_save(bpy.types.Operator):
    bl_idname = "mge.save_mod"
    bl_label = "Als Mod speichern"
    bl_description = "Die geänderten Zonen in den Ziel-Mod schreiben und ihn in mods.txt einschalten"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def execute(self, context):
        out = export_mod(self, context)
        if out is None:
            return {"CANCELLED"}
        if not out:
            self.report({"INFO"}, "Keine Änderungen")
        else:
            self.report({"INFO"}, f"Gespeichert in mods/{context.scene.mge_mod}: {', '.join(out)}")
            # The objects now stand for the saved rows: an undo step, so Ctrl+Z first returns here.
            if not bpy.app.background:
                bpy.ops.ed.undo_push(message="Galaxie gespeichert")
        return {"FINISHED"}


class MGE_OT_save_shortcut(bpy.types.Operator):
    bl_idname = "mge.save_shortcut"
    bl_label = "Mod speichern (⌘S)"
    bl_description = "Im Arbeitsbereich Galaxie speichert ⌘S den Mod; sonst wie gewohnt die .blend-Datei"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy")) and context.workspace is not None and \
            context.workspace.name == workspace.NAME

    def execute(self, context):
        return bpy.ops.mge.save_mod()


class MGE_OT_preview(bpy.types.Operator):
    bl_idname = "mge.preview"
    bl_label = "Automatisch testen (Bilder)"
    bl_description = ("Speichern, dann die Galaxie unsichtbar im Spiel laden (eigener Wegwerf-Spielstand), Mario laufen "
                      "lassen und Bilder zeigen; mit dem Startpunkt-Knopf beginnt Mario am Vorschau-Startpunkt")
    _timer = None

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def execute(self, context):
        if export_mod(self, context) is None:
            return {"CANCELLED"}
        scene = context.scene
        warp = tuple(to_game(scene.cursor.location)) if scene.mge_warp else None
        try:
            self.preview = game_io.Preview(game_data(scene), scene["smg_galaxy"], int(scene.mge_scenario), warp)
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self._timer = context.window_manager.event_timer_add(1.0, window=context.window)
        context.window_manager.modal_handler_add(self)
        scene.mge_status = "Automatischer Test läuft …"
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        result = self.preview.poll()
        if result is None:
            return {"PASS_THROUGH"}
        context.window_manager.event_timer_remove(self._timer)
        passed, summary, pictures = result
        last = summary[-1] if summary else ""
        context.scene.mge_status = "Test bestanden ✓" if passed else f"Problem: {last[-80:]}"
        for line in summary:
            print(line)
        if pictures and not _show_in_image_editor(context, pictures):
            subprocess.Popen(["open", "-a", "Preview", *map(str, pictures)])
        self.report({"INFO" if passed else "WARNING"}, (summary[-1] if summary else "keine Ausgabe")[:200])
        return {"FINISHED"}


def _show_in_image_editor(context, pictures):
    """The run's pictures into the window's image editor (MacioGalaxy Studio has one); False without one."""
    editors = [a for a in context.window.screen.areas if a.type == "IMAGE_EDITOR"]
    if not editors:
        return False
    images = [bpy.data.images.load(str(p), check_existing=True) for p in pictures]
    for image in images:
        image.reload()
    editors[0].spaces[0].image = images[-1]
    context.scene["mge_preview_pictures"] = [image.name for image in images]
    editors[0].tag_redraw()
    return True


class MGE_OT_play(bpy.types.Operator):
    bl_idname = "mge.play"
    bl_label = "Selbst spielen"
    bl_description = "Speichern und das Spiel starten: nach dem Laden eines Spielstands geht es direkt in diese Galaxie"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def execute(self, context):
        if export_mod(self, context) is None:
            return {"CANCELLED"}
        try:
            game_io.play(context.scene["smg_galaxy"], int(context.scene.mge_scenario))
        except RuntimeError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


# --- registration ----------------------------------------------------------------------------


@persistent
def _gravity_handler(scene, depsgraph):
    """Redraws gravity ranges, and adopts objects dropped from the asset library (after the update)."""
    dropped = []
    for update in depsgraph.updates:
        obj = getattr(update.id, "original", None)
        if not isinstance(obj, bpy.types.Object):
            continue
        if obj.get("smg_kind") and scene.get("mge_armed") and not scene.get("mge_dirty") and \
                (update.is_updated_transform or update.is_updated_geometry):
            scene["mge_dirty"] = True
        if obj.get("smg_kind") == "planetobjinfo" and obj.type == "MESH":
            scene_io.refresh_gravity(obj)
        elif obj.get("smg_asset_name") and not obj.get("smg_kind") and scene.get("smg_galaxy"):
            dropped.append(obj.name)
    if scene.get("mge_armed") and not scene.get("mge_dirty") and _object_count(scene) != scene.get("mge_count"):
        scene["mge_dirty"] = True  # an object deleted (or added outside the tools)
    if dropped:
        bpy.app.timers.register(lambda: _adopt(dropped), first_interval=0.0)


def _adopt(names):
    context = bpy.context
    for name in names:
        obj = bpy.data.objects.get(name)
        if obj is not None and obj.get("smg_asset_name") and not obj.get("smg_kind"):
            assets.adopt_dropped(context, obj, sys.modules[__name__])
    return None


CLASSES = (MGE_OT_open, MGE_OT_add, MGE_OT_add_path, MGE_OT_save, MGE_OT_save_shortcut, MGE_OT_preview, MGE_OT_play,
           MGE_OT_mod_toggle, MGE_OT_view_start)
_keymaps = []


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mge_user = StringProperty(name="Spielordner", subtype="DIR_PATH", default=str(USER),
                                              description="Benutzerordner von MacioGalaxy (Disc, Mods, mods.txt)")
    bpy.types.Scene.mge_galaxy = StringProperty(name="Galaxie", search=_galaxy_search, default="Good Egg Galaxy (EggStarGalaxy)",
                                                description="Name im Spiel oder interner Name (Sternenschiff: AstroGalaxy)")
    bpy.types.Scene.mge_scenario = EnumProperty(name="Szenario", items=_scenarios, update=_scenario_changed)
    bpy.types.Scene.mge_mod = StringProperty(name="Ziel-Mod", default="",
                                             description="Mod-Ordner, in den gespeichert wird (mods/<Name>)")
    bpy.types.Scene.mge_warp = BoolProperty(name="Am 3D-Cursor starten", default=False)
    bpy.types.Scene.mge_models = BoolProperty(name="Modelle", default=True, update=_models_changed,
                                              description="Die Modelle des Spiels zeigen statt der Platzhalter-Würfel")
    bpy.types.Scene.mge_status = StringProperty(default="")
    ui.register()
    tools.register()
    workspace.register()
    shelf.register()
    hud.register()
    bpy.app.handlers.depsgraph_update_post.append(_gravity_handler)
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is not None:
        keymap = keyconfig.keymaps.new(name="Window", space_type="EMPTY")
        for modifier in ("oskey", "ctrl"):
            item = keymap.keymap_items.new(MGE_OT_save_shortcut.bl_idname, "S", "PRESS", **{modifier: True})
            _keymaps.append((keymap, item))


def unregister():
    for keymap, item in _keymaps:
        keymap.keymap_items.remove(item)
    _keymaps.clear()
    if _gravity_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_gravity_handler)
    hud.unregister()
    shelf.unregister()
    workspace.unregister()
    tools.unregister()
    ui.unregister()
    for name in ("mge_user", "mge_galaxy", "mge_scenario", "mge_mod", "mge_warp", "mge_status", "mge_models"):
        delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

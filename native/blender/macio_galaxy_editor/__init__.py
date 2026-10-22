"""MacioGalaxy editor: Super Mario Galaxy levels in Blender (native/blender/README.md).

Opens a galaxy (the disc with the enabled mods on top) as objects, areas, gravity and paths in the
scene, edits them with Blender's own tools, saves the changed zones as a MacioGalaxy mod, and plays
them, headless with pictures or in the game. The sidebar's "Galaxy" tab (N in the 3D view).
"""
bl_info = {
    "name": "MacioGalaxy Editor",
    "author": "rzrnr",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D View > Sidebar > Galaxy",
    "description": "Edit Super Mario Galaxy levels and play them in MacioGalaxy",
    "category": "Import-Export",
}

import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

import bpy  # noqa: E402
from bpy.app.handlers import persistent  # noqa: E402
from bpy.props import BoolProperty, EnumProperty, StringProperty  # noqa: E402

from . import game as game_io  # noqa: E402
from . import scene_io  # noqa: E402
from .catalog import KIND_LABEL, Catalog  # noqa: E402
from .models import ModelLibrary  # noqa: E402
from .convert import basis_from_game, to_game  # noqa: E402
from .galaxy import USER, GameData, Path_, PathPoint, read_tree  # noqa: E402

_cache = {}


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
    items = [(str(s.no), f"{s.no}: {s.name}", s.name) for s in galaxy.scenarios]
    _cache["scenario_items"] = items  # Blender needs the strings kept alive
    return items


def _models_changed(self, context):
    scene = context.scene
    root = bpy.data.collections.get(f"SMG {scene.get('smg_galaxy')}")
    if root is not None:
        scene_io.show_models(root, model_library(scene))


def _scenario_changed(self, context):
    scene = context.scene
    if scene.get("smg_galaxy"):
        scene["smg_scenario"] = int(scene.mge_scenario)
        scene_io.apply_scenario(scene, open_galaxy(scene))


# --- operators -------------------------------------------------------------------------------


class MGE_OT_open(bpy.types.Operator):
    bl_idname = "mge.open_galaxy"
    bl_label = "Galaxie öffnen"
    bl_description = "Die gewählte Galaxie (Disc und eingeschaltete Mods) in die Szene holen; eine offene wird ersetzt"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scene = context.scene
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
        if not scene.mge_mod:
            origin = scene.get("smg_main_origin")
            scene.mge_mod = origin if origin and origin != "disc" else "BlenderEdits"
        _setup_views(context)
        self.report({"INFO"}, f"{name}: {count} Objekte und Paths in {len(galaxy.zone_names)} Zonen")
        return {"FINISHED"}


def _setup_views(context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.shading.color_type = "TEXTURE"
                        space.shading.wireframe_color_type = "OBJECT"
                        space.clip_end = max(space.clip_end, 20000.0)


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
        coll = bpy.data.collections.get(f"{zone} Paths") or _target_collection(context)
        for point in points:
            point.values.update({f"point_arg{k}": -1 for k in range(8)})
        obj = scene_io.make_path(Path_(zone, -1, values, points), zone, coll, parent)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class MGE_OT_scenario(bpy.types.Operator):
    bl_idname = "mge.apply_scenario"
    bl_label = "Ebenen des Szenarios zeigen"
    bl_options = {"REGISTER"}

    def execute(self, context):
        scene_io.apply_scenario(context.scene, open_galaxy(context.scene))
        return {"FINISHED"}


def export_mod(operator, context):
    """Writes the changed zones into the target mod; returns the zones written (or None on error)."""
    scene = context.scene
    galaxy = open_galaxy(scene)
    mod = scene.mge_mod.strip() or "BlenderEdits"
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
        return {"FINISHED"}


class MGE_OT_preview(bpy.types.Operator):
    bl_idname = "mge.preview"
    bl_label = "Vorschau (unsichtbar)"
    bl_description = ("Speichern, dann die Galaxie headless spielen (Wegwerf-Spielstand) und Bilder zeigen; "
                      "mit Warp startet Mario am 3D-Cursor")
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
        scene.mge_status = "Vorschau läuft …"
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        result = self.preview.poll()
        if result is None:
            return {"PASS_THROUGH"}
        context.window_manager.event_timer_remove(self._timer)
        passed, summary, pictures = result
        context.scene.mge_status = ("Vorschau: läuft" if passed else "Vorschau: Problem") + f" ({self.preview.run.name})"
        for line in summary:
            print(line)
        if pictures:
            subprocess.Popen(["open", "-a", "Preview", *map(str, pictures)])
        self.report({"INFO" if passed else "WARNING"}, (summary[-1] if summary else "keine Ausgabe")[:200])
        return {"FINISHED"}


class MGE_OT_play(bpy.types.Operator):
    bl_idname = "mge.play"
    bl_label = "Im Spiel starten"
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


# --- panels ----------------------------------------------------------------------------------


class MGE_PT_galaxy(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", "Galaxy"
    bl_label = "Galaxie"

    def draw(self, context):
        scene, layout = context.scene, self.layout
        layout.prop(scene, "mge_galaxy", text="", icon="WORLD")
        layout.operator(MGE_OT_open.bl_idname, icon="FILE_FOLDER")
        if scene.get("smg_galaxy"):
            layout.prop(scene, "mge_scenario", text="Szenario")
            layout.prop(scene, "mge_models", text="Modelle des Spiels", icon="MESH_MONKEY")
            box = layout.box()
            box.label(text=f"Offen: {galaxy_label(scene, scene['smg_galaxy'])}")
            col = box.column(align=True)
            col.operator(MGE_OT_add.bl_idname, text="Objekt", icon="ADD").kind = "OBJECT"
            col.operator(MGE_OT_add.bl_idname, text="Gravity", icon="FORCE_FORCE").kind = "GRAVITY"
            col.operator(MGE_OT_add.bl_idname, text="Area", icon="MESH_CUBE").kind = "AREA"
            col.operator(MGE_OT_add.bl_idname, text="Alle Arten", icon="VIEWZOOM").kind = "ALL"
            col.operator(MGE_OT_add_path.bl_idname, icon="CURVE_BEZCURVE")
            box.label(text="Ziel: aktive Ebene (Outliner)", icon="INFO")


class MGE_PT_object(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", "Galaxy"
    bl_label = "Auswahl"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and context.active_object.get("smg_kind")

    def draw(self, context):
        obj, layout = context.active_object, self.layout
        kind = obj["smg_kind"]
        name = obj.get(scene_io.PREFIX + "name", "")
        cat = catalog(context.scene)
        entry = cat.entries.get(name)
        layout.label(text=f"{KIND_LABEL.get(kind, kind)} in {obj['smg_zone']} · {scene_io._layer_of(obj)}")
        if entry and entry["label"] != name:
            layout.label(text=entry["label"])
        if entry and entry["notes"]:
            col = layout.column(align=True)
            for line in _wrap(entry["notes"], 48)[:6]:
                col.label(text=line)
        col = layout.column(align=True)
        for key in sorted((k for k in obj.keys() if k.startswith(scene_io.PREFIX)), key=_field_order):
            field = key[len(scene_io.PREFIX):]
            info = cat.parameter(name, field)
            col.prop(obj, f'["{key}"]', text=f"{field} · {info[0]}" if info else field)
        if kind == "path":
            layout.label(text="Punkte: Bearbeitungsmodus (Tab), Griffe = Kontrollpunkte")


def _field_order(key):
    order = ["name", "l_id", "Obj_arg", "Range", "Distant", "SW_", "CommonPath_ID", "CameraSetId", "MessageId"]
    field = key[len(scene_io.PREFIX):]
    return next((i for i, prefix in enumerate(order) if field.startswith(prefix)), len(order)), field


def _wrap(text, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + ([line] if line else [])


class MGE_PT_game(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", "Galaxy"
    bl_label = "Spiel"

    def draw(self, context):
        scene, layout = context.scene, self.layout
        layout.prop(scene, "mge_mod", text="Mod")
        layout.operator(MGE_OT_save.bl_idname, icon="FILE_TICK")
        row = layout.row(align=True)
        row.operator(MGE_OT_preview.bl_idname, icon="RENDER_STILL")
        row.prop(scene, "mge_warp", text="", icon="PIVOT_CURSOR")
        layout.operator(MGE_OT_play.bl_idname, icon="PLAY")
        if scene.mge_status:
            layout.label(text=scene.mge_status)
        layout.prop(scene, "mge_user", text="Spielordner")


# --- registration ----------------------------------------------------------------------------


@persistent
def _gravity_handler(scene, depsgraph):
    for update in depsgraph.updates:
        obj = getattr(update.id, "original", None)
        if isinstance(obj, bpy.types.Object) and obj.get("smg_kind") == "planetobjinfo" and obj.type == "MESH":
            scene_io.refresh_gravity(obj)


CLASSES = (MGE_OT_open, MGE_OT_add, MGE_OT_add_path, MGE_OT_scenario, MGE_OT_save, MGE_OT_preview, MGE_OT_play,
           MGE_PT_galaxy, MGE_PT_object, MGE_PT_game)


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
    bpy.app.handlers.depsgraph_update_post.append(_gravity_handler)


def unregister():
    if _gravity_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_gravity_handler)
    for name in ("mge_user", "mge_galaxy", "mge_scenario", "mge_mod", "mge_warp", "mge_status", "mge_models"):
        delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

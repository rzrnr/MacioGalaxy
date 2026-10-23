"""The editor's interface: two sidebar tabs in the 3D view (N), beside the toolbar (tools.py), the
object palette (shelf.py) and the viewport's HUD (hud.py).

- Galaxie: a welcome checklist and the galaxy to open; once open: Spielen (save, quick test, test play
  in the testbed, start the whole game, the mod on or off), the scenarios (with the layers each uses),
  the zones (an eye and a solo button each) and the selected zone's layers, the switches for what is drawn (their colour swatches
  are the legend of the viewport's wire shapes), and the object list (search, kind, zone).
- Objekt: the selected object: picture, description, layer, place in the game's coordinates, and its
  fields in groups (arguments with what they mean and a menu of their values, switches, links with
  the message's text and a path chooser, the rest).
"""
import json
import sys

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatVectorProperty, IntProperty,
                       IntVectorProperty, PointerProperty, StringProperty)

from . import scene_io
from .catalog import KIND_LABEL
from .convert import basis_from_game, game_from_basis
from .galaxy import LAYERS
from .models import archive_name
from .thumbnails import Thumbnails

TAB = {"galaxy": "Galaxie", "props": "Objekt"}
GROUP_LABELS = [("objects", "Objekte", "OBJECT_DATA"), ("mapparts", "Levelteile", "MESH_CUBE"),
                ("areas", "Bereiche", "CUBE"), ("cameras", "Kamerabereiche", "CAMERA_DATA"),
                ("gravity", "Schwerkraft", "FORCE_FORCE"), ("starts", "Startpunkte", "ARMATURE_DATA"),
                ("paths", "Pfade", "CURVE_BEZCURVE"), ("zones", "Zonen", "EMPTY_AXIS"), ("sky", "Himmel", "WORLD"),
                ("other", "Sonstiges", "SOUND")]
GROUP_COLOUR = {"objects": "objinfo", "mapparts": "mappartsinfo", "areas": "areaobjinfo", "cameras": "cameracubeinfo",
                "gravity": "planetobjinfo", "starts": "startinfo", "zones": "stageobjinfo"}
KIND_ICON = {"objinfo": "OBJECT_DATA", "childobjinfo": "OBJECT_DATA", "mappartsinfo": "MESH_CUBE", "areaobjinfo": "CUBE",
             "cameracubeinfo": "CAMERA_DATA", "planetobjinfo": "FORCE_FORCE", "startinfo": "ARMATURE_DATA",
             "path": "CURVE_BEZCURVE", "stageobjinfo": "EMPTY_AXIS", "soundinfo": "SOUND", "generalposinfo": "EMPTY_DATA",
             "debugmoveinfo": "EMPTY_DATA", "demoobjinfo": "SEQUENCE"}
LINK_FIELDS = ("CommonPath_ID", "CameraSetId", "MessageId", "CastId", "GroupId", "ClippingGroupId", "DemoGroupId",
               "MapParts_ID", "ViewGroupId", "ShapeModelNo", "FollowId", "ChildObjId", "Obj_ID", "ParentID", "Camera_id",
               "MarioNo")
GRAVITY_FIELDS = ("Range", "Distant", "Priority", "Inverse", "Power", "Gravity_type")
_state = {"thumbs": None, "syncing": False}


def editor():
    """The package (its helpers and operators live in __init__)."""
    return sys.modules[__package__]


def thumbs():
    if _state["thumbs"] is None:
        _state["thumbs"] = Thumbnails()
    return _state["thumbs"]


def galaxy_root(scene):
    return bpy.data.collections.get(f"SMG {scene.get('smg_galaxy')}") if scene.get("smg_galaxy") else None


# --- visibility ------------------------------------------------------------------------------


class MGE_Layer(bpy.types.PropertyGroup):
    visible: BoolProperty(default=True, update=lambda self, context: apply_visibility(context.scene))
    in_scenario: BoolProperty(default=True)


class MGE_Zone(bpy.types.PropertyGroup):
    label: StringProperty()
    visible: BoolProperty(default=True, update=lambda self, context: apply_visibility(context.scene))
    in_scenario: BoolProperty(default=True)
    layers: CollectionProperty(type=MGE_Layer)
    layer_index: IntProperty()


def apply_visibility(scene):
    root = galaxy_root(scene)
    if root is None:
        return
    zones = {z.name: z.visible for z in scene.mge_zones}
    layers = {z.name: {layer.name for layer in z.layers if layer.visible} for z in scene.mge_zones}
    groups = {key for key, _, _ in GROUP_LABELS if getattr(scene, f"mge_show_{key}")}
    scene_io.apply_visibility(root, zones, layers, groups)


def sync_zones(scene, galaxy):
    """The zone list after opening a galaxy: every zone with the layers it has."""
    scene.mge_zones.clear()
    root = galaxy_root(scene)
    for zone_name in galaxy.zone_names:
        item = scene.mge_zones.add()
        item.name = zone_name
        item.label = "Hauptzone" if zone_name == galaxy.name else ""
        zone_coll = root.children.get(zone_name) if root else None
        present = {c.get("smg_layer") for c in zone_coll.children} if zone_coll else set()
        for layer in LAYERS:
            if layer in present:
                entry = item.layers.add()
                entry.name = layer
    apply_scenario(scene, galaxy)


def apply_scenario(scene, galaxy):
    """Turns on what the scenario uses: its layers and the zones it places; the rest off."""
    scenario = galaxy.scenario(int(scene.mge_scenario))
    for zone in scene.mge_zones:
        active = zone.name == galaxy.name or scenario.masks.get(zone.name, 0) != 0 or zone.name not in scenario.masks
        zone.in_scenario = active
        zone["visible"] = active
        used = scenario.layers(zone.name)
        for layer in zone.layers:
            layer.in_scenario = layer.name in used
            layer["visible"] = layer.name in used
    apply_visibility(scene)


class MGE_UL_zones(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.prop(item, "visible", text="", emboss=False, icon="HIDE_OFF" if item.visible else "HIDE_ON")
        label = f"{item.name}  ({item.label})" if item.label else item.name
        row.label(text=label, icon="WORLD" if item.label else ("DOT" if item.in_scenario else "BLANK1"))
        row.operator(MGE_OT_zone_solo.bl_idname, text="", icon="SOLO_ON" if _solo(context, item) else "SOLO_OFF",
                     emboss=False).zone = item.name


def _solo(context, item):
    return item.visible and all(not z.visible for z in context.scene.mge_zones if z.name != item.name)


class MGE_OT_zone_solo(bpy.types.Operator):
    bl_idname = "mge.zone_solo"
    bl_label = "Nur diese Zone"
    bl_description = "Nur diese Zone zeigen (noch einmal: wieder alle Zonen des Szenarios)"
    zone: StringProperty()

    def execute(self, context):
        scene = context.scene
        item = next((z for z in scene.mge_zones if z.name == self.zone), None)
        if item is None:
            return {"CANCELLED"}
        if _solo(context, item):
            apply_scenario(scene, editor().open_galaxy(scene))
            return {"FINISHED"}
        for zone in scene.mge_zones:
            zone["visible"] = zone.name == self.zone
        apply_visibility(scene)
        return {"FINISHED"}


class MGE_UL_layers(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.prop(item, "visible", text="", emboss=False, icon="HIDE_OFF" if item.visible else "HIDE_ON")
        row.label(text=layer_label(item.name), icon="CHECKMARK" if item.in_scenario else "BLANK1")


def scenario_hint(scene, zone_name, layer_name):
    """"" when the zone and layer appear in the chosen scenario, else a warning to add to a report."""
    zone = next((z for z in scene.mge_zones if z.name == zone_name), None)
    if zone is None:
        return ""
    if not zone.in_scenario:
        return f" – Achtung: die Zone {zone_name} kommt im gewählten Szenario nicht vor"
    layer = next((x for x in zone.layers if x.name == layer_name), None)
    if layer is not None and not layer.in_scenario:
        return f" – Achtung: {layer_label(layer_name)} kommt im gewählten Szenario nicht vor"
    return ""


def layer_label(layer):
    return "Gemeinsam" if layer == "common" else f"Ebene {layer[-1].upper()}"


class MGE_OT_zones_all(bpy.types.Operator):
    bl_idname = "mge.zones_all"
    bl_label = "Alle Zonen"
    bl_description = "Alle Zonen und Ebenen zeigen, oder nur die des Szenarios"
    mode: EnumProperty(items=[("ALL", "Alle", ""), ("SCENARIO", "Szenario", "")])

    def execute(self, context):
        scene = context.scene
        if self.mode == "SCENARIO":
            apply_scenario(scene, editor().open_galaxy(scene))
            return {"FINISHED"}
        for zone in scene.mge_zones:
            zone["visible"] = True
            for layer in zone.layers:
                layer["visible"] = True
        apply_visibility(scene)
        return {"FINISHED"}


# --- the object list -------------------------------------------------------------------------


def _kept(key, make):
    """An enum's items, built once per key and kept (Blender holds on to the strings it was given)."""
    items = _state.setdefault("enums", {})
    if key not in items:
        items[key] = make()
    return items[key]


def _browse_zones(self, context):
    zones = tuple(z.name for z in context.scene.mge_zones)
    return _kept(("zones", zones), lambda: [("ALL", "Alle Zonen", "")] + [(z, z, "") for z in zones])


class MGE_UL_objects(bpy.types.UIList):
    """The galaxy's placed objects, from bpy.data.objects, filtered."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        kind = item.get("smg_kind", "")
        name = item.get(scene_io.PREFIX + "name", item.name)
        cat = editor().catalog(context.scene)
        entry = cat.entries.get(name)
        row = layout.row(align=True)
        picture = thumbs().icon(archive_name(name, scene_io.fields_of(item))) if kind in scene_io.MODEL_KINDS else 0
        if picture:
            row.label(text="", icon_value=picture)
        else:
            row.label(text="", icon=KIND_ICON.get(kind, "DOT"))
        shown = entry["label"] if entry and entry["label"] != name else ""
        split = row.split(factor=0.62, align=True)
        split.label(text=f"{shown} · {name}" if shown else name)
        layer = "Pfad" if kind == "path" else layer_label(scene_io._layer_of(item))
        ident = item.get(scene_io.PREFIX + "l_id")
        split.label(text=f"{layer} · ID {ident}" if isinstance(ident, int) and ident >= 0 else layer)

    def filter_items(self, context, data, propname):
        scene = context.scene
        objects = getattr(data, propname)
        root = galaxy_root(scene)
        members = set(root.all_objects) if root else set()
        kinds = scene_io.GROUPS.get(scene.mge_browse_group)
        zone = scene.mge_browse_zone
        text = (scene.mge_object_search or self.filter_name).lower()
        cat = editor().catalog(scene)
        flags = []
        for obj in objects:
            kind = obj.get("smg_kind")
            ok = obj in members and kind is not None
            ok = ok and (kinds is None or kind in kinds) and (zone == "ALL" or obj.get("smg_zone") == zone)
            if ok and text:
                name = obj.get(scene_io.PREFIX + "name", obj.name)
                entry = cat.entries.get(name)
                ok = text in name.lower() or (entry is not None and text in entry["label"].lower())
            flags.append(self.bitflag_filter_item if ok else 0)
        order = sorted(range(len(objects)), key=lambda i: (objects[i].get(scene_io.PREFIX + "name", objects[i].name).lower(), i))
        ranks = [0] * len(objects)
        for rank, i in enumerate(order):
            ranks[i] = rank
        return flags, ranks


def _object_index_changed(self, context):
    if _state["syncing"]:
        return
    scene = context.scene
    if 0 <= scene.mge_object_index < len(bpy.data.objects):
        obj = bpy.data.objects[scene.mge_object_index]
        if obj.name in context.view_layer.objects:
            for other in context.selected_objects:
                other.select_set(False)
            if obj.hide_get():
                obj.hide_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj


def _active_changed():
    """The viewport's active object -> the list's highlight."""
    context = bpy.context
    obj = getattr(context, "active_object", None)
    if obj is None or not obj.get("smg_kind"):
        return
    index = bpy.data.objects.find(obj.name)
    scene = context.scene
    if index >= 0 and scene.mge_object_index != index:
        _state["syncing"] = True
        scene.mge_object_index = index
        _state["syncing"] = False


class MGE_OT_frame(bpy.types.Operator):
    bl_idname = "mge.frame_selected"
    bl_label = "Zeigen"
    bl_description = "Die Ansicht auf das gewählte Objekt richten"

    def execute(self, context):
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    region = next(r for r in area.regions if r.type == "WINDOW")
                    with context.temp_override(window=window, area=area, region=region):
                        bpy.ops.view3d.view_selected()
                    return {"FINISHED"}
        return {"CANCELLED"}


# --- the catalog -----------------------------------------------------------------------------


class MGE_CatalogItem(bpy.types.PropertyGroup):
    label: StringProperty()
    kind: StringProperty()
    category: StringProperty()
    archive: StringProperty()
    notes: StringProperty()


def _categories(self, context):
    seen = tuple(sorted({i.category for i in context.window_manager.mge_catalog if i.category}))

    def make():
        items = [("ALL", "Alle", "Alle Objekte des Spiels")]
        items += [(key, label, "") for key, label, _ in GROUP_LABELS if key in ("objects", "mapparts", "areas", "cameras",
                                                                                  "gravity", "starts")]
        return items + [(f"cat:{c}", c, "Kategorie der Objektdatenbank") for c in seen]
    return _kept(("categories", seen), make)


def fill_catalog(context):
    """The window manager's catalog list from the catalog (once per game folder)."""
    wm = context.window_manager
    cat = editor().catalog(context.scene)
    if len(wm.mge_catalog) and wm.get("mge_catalog_user") == context.scene.mge_user:
        return
    wm.mge_catalog.clear()
    for name in cat.names():
        entry = cat.entries[name]
        item = wm.mge_catalog.add()
        item.name, item.label, item.kind = name, entry["label"], entry["kind"]
        item.category, item.notes = entry.get("category", ""), entry.get("notes", "")[:600]
        item.archive = archive_name(name, cat.defaults(name))
    wm["mge_catalog_user"] = context.scene.mge_user


def _catalog_chosen(self, context):
    """The catalog's choice is also what the Setzen tool places."""
    wm = context.window_manager
    if 0 <= wm.mge_catalog_index < len(wm.mge_catalog) and hasattr(wm, "mge_tool_object"):
        wm.mge_tool_object = wm.mge_catalog[wm.mge_catalog_index].name


class MGE_UL_catalog(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        picture = thumbs().icon(item.archive)
        row = layout.row(align=True)
        if picture:
            row.label(text="", icon_value=picture)
        else:
            row.label(text="", icon=KIND_ICON.get(item.kind, "DOT"))
        row.label(text=item.name if item.label == item.name else f"{item.label}  ({item.name})")

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        wanted = context.window_manager.mge_catalog_filter
        kinds = scene_io.GROUPS.get(wanted)
        text = self.filter_name.lower()
        flags = []
        for item in items:
            ok = wanted == "ALL" or (kinds is not None and item.kind in kinds) or \
                (wanted.startswith("cat:") and item.category == wanted[4:])
            ok = ok and (not text or text in item.name.lower() or text in item.label.lower())
            flags.append(self.bitflag_filter_item if ok else 0)
        return flags, []


class MGE_OT_place(bpy.types.Operator):
    bl_idname = "mge.place_catalog"
    bl_label = "Am 3D-Cursor einfügen"
    bl_description = "Das gewählte Objekt des Katalogs am 3D-Cursor in die aktive Ebene setzen"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        wm = context.window_manager
        return bool(context.scene.get("smg_galaxy")) and 0 <= wm.mge_catalog_index < len(wm.mge_catalog)

    def execute(self, context):
        wm = context.window_manager
        name = wm.mge_catalog[wm.mge_catalog_index].name
        op = editor().MGE_OT_add
        stub = type("Add", (), {"item": name, "kind": "ALL", "report": self.report})()
        return op.execute(stub, context)


class MGE_OT_build_assets(bpy.types.Operator):
    bl_idname = "mge.build_assets"
    bl_label = "Objekt-Palette aufbauen"
    bl_description = ("Den Katalog als Asset-Bibliothek \"Mario Galaxy\" anlegen (im Hintergrund): die Objekte des Spiels "
                      "im Asset Browser, zum Hineinziehen in die Szene")
    _timer = None

    def execute(self, context):
        from . import assets
        assets.register_library(context)
        self.process = assets.start_build(editor().catalog(context.scene), editor().game_data(context.scene).user)
        context.scene.mge_status = "Objekt-Palette wird aufgebaut …"
        self._timer = context.window_manager.event_timer_add(1.0, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER" or self.process.poll() is None:
            return {"PASS_THROUGH"}
        context.window_manager.event_timer_remove(self._timer)
        from . import shelf
        shelf._names.clear()
        # The palette (asset shelf) and any Asset Browser read the library again.
        for area in context.screen.areas:
            for region in area.regions if area.type in ("VIEW_3D", "FILE_BROWSER") else []:
                if region.type in ("ASSET_SHELF", "WINDOW"):
                    with context.temp_override(area=area, region=region):
                        if bpy.ops.asset.library_refresh.poll():
                            bpy.ops.asset.library_refresh()
                            break
        context.scene.mge_status = "Objekt-Palette fertig: Asset Browser, Bibliothek \"Mario Galaxy\""
        for area in context.screen.areas:
            area.tag_redraw()
        return {"FINISHED"}


class MGE_OT_thumbnails(bpy.types.Operator):
    bl_idname = "mge.thumbnails"
    bl_label = "Vorschaubilder erzeugen"
    bl_description = ("Die Modelle des Katalogs einmalig im Hintergrund rendern (ein zweites, unsichtbares Blender, "
                      "wartet, solange das Spiel läuft)")
    _timer = None

    def execute(self, context):
        fill_catalog(context)
        cat = editor().catalog(context.scene)
        items = [(i.name, cat.defaults(i.name), i.archive) for i in context.window_manager.mge_catalog
                 if i.kind in scene_io.MODEL_KINDS]
        count = thumbs().start(items, editor().game_data(context.scene).user)
        if not count:
            self.report({"INFO"}, "Alle Vorschaubilder sind da")
            return {"FINISHED"}
        context.scene.mge_status = f"Vorschaubilder: {count} werden gerendert …"
        self._timer = context.window_manager.event_timer_add(2.0, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        for area in context.screen.areas:
            area.tag_redraw()
        if not thumbs().running():
            context.window_manager.event_timer_remove(self._timer)
            context.scene.mge_status = "Vorschaubilder fertig"
            return {"FINISHED"}
        return {"PASS_THROUGH"}


# --- the selected object ---------------------------------------------------------------------


def _game_transform(obj):
    """{pos, rot, scale} in game units; rot as the zone stores it while the object is turned as then."""
    matrix = scene_io._zone_local(obj)
    pos, rot, scale = game_from_basis(matrix)
    return {"pos": pos, "rot": scene_io.stored_dir(obj, matrix) or rot, "scale": scale}


def _get_transform(part):
    def get(obj):
        if not obj.get("smg_kind") or obj.get("smg_kind") == "path":
            return (0.0, 0.0, 0.0)
        return _game_transform(obj)[part]
    return get


def _set_transform(part):
    def set_(obj, value):
        if not obj.get("smg_kind") or obj.get("smg_kind") == "path":
            return
        values = _game_transform(obj)
        values[part] = list(value)
        scene_io.set_zone_local(obj, basis_from_game(values["pos"], values["rot"], values["scale"]))
        # The typed angles are what the zone gets (one axis changed: the other two stay as they were).
        scene_io.remember_dir(obj, values["rot"])
        mark_dirty(bpy.context.scene)
    return set_


def _layers_of_zone(self, context):
    obj = context.active_object
    zone = next((z for z in context.scene.mge_zones if obj and z.name == obj.get("smg_zone")), None)
    names = [layer.name for layer in zone.layers] if zone else ["common"]
    for layer in LAYERS:  # any layer can be used; the zone gets it when saved
        if layer not in names:
            names.append(layer)
    return _kept(("layers", tuple(names)),
                 lambda: [(n, "Gemeinsam" if n == "common" else f"Ebene {n[-1].upper()}", n) for n in names])


class MGE_OT_set_layer(bpy.types.Operator):
    bl_idname = "mge.set_layer"
    bl_label = "Ebene"
    bl_description = "Die gewählten Objekte in eine andere Ebene ihrer Zone legen (Ebene = was in welchem Szenario erscheint)"
    bl_options = {"REGISTER", "UNDO"}
    layer: EnumProperty(items=_layers_of_zone)

    def execute(self, context):
        root = galaxy_root(context.scene)
        moved = 0
        for obj in context.selected_objects or [context.active_object]:
            if not obj.get("smg_kind") or obj.get("smg_kind") in ("path", "stageobjinfo"):
                continue
            target = scene_io.layer_collection(root, obj["smg_zone"], self.layer)
            for coll in list(obj.users_collection):
                coll.objects.unlink(obj)
            target.objects.link(obj)
            _ensure_layer(context.scene, obj["smg_zone"], self.layer)
            moved += 1
        apply_visibility(context.scene)
        zone = next((z for z in context.scene.mge_zones if z.name == context.active_object.get("smg_zone")), None)
        layer = next((x for x in zone.layers if x.name == self.layer), None) if zone else None
        mark_dirty(context.scene)
        hint = "" if layer is None or layer.in_scenario else f"; {layer_label(self.layer)} kommt im gewählten Szenario nicht vor"
        self.report({"INFO"}, f"{moved} Objekt(e) nach {layer_label(self.layer)}{hint}")
        return {"FINISHED"}


def _zones_to_move_to(self, context):
    zones = tuple(z.name for z in context.scene.mge_zones)
    return _kept(("move", zones), lambda: [(z, z, "") for z in zones])


class MGE_OT_move_zone(bpy.types.Operator):
    bl_idname = "mge.move_zone"
    bl_label = "Zone"
    bl_description = ("Die gewählten Objekte und Pfade in eine andere Zone legen: sie bleiben, wo sie in der Galaxie "
                      "stehen, und werden dort neue Zeilen (in derselben Ebene; Pfade bekommen eine freie ID)")
    bl_options = {"REGISTER", "UNDO"}
    zone: EnumProperty(items=_zones_to_move_to)

    def execute(self, context):
        from mathutils import Matrix
        core = editor()
        root = galaxy_root(context.scene)
        parent = core._zone_parent(context, self.zone)
        moved = skipped = 0
        for obj in context.selected_objects or [context.active_object]:
            kind = obj.get("smg_kind")
            if not kind or kind == "stageobjinfo" or obj.get("smg_zone") == self.zone:
                continue
            if obj.parent is not None and obj.parent.get("smg_kind") != "stageobjinfo":
                skipped += 1  # parented to another object: it moves with that one
                continue
            world = obj.matrix_world.copy()
            before = scene_io._zone_local(obj).decompose()[1]
            rot = scene_io.stored_dir(obj)
            if kind == "path":
                target = scene_io._collection(scene_io.paths_collection_name(self.zone),
                                              scene_io._collection(self.zone, root))
                obj[scene_io.PREFIX + "l_id"] = -1  # a free ID in the new zone, when saving
            else:
                layer = scene_io._layer_of(obj)
                target = scene_io.layer_collection(root, self.zone, layer)
                _ensure_layer(context.scene, self.zone, layer)
            for coll in list(obj.users_collection):
                coll.objects.unlink(obj)
            target.objects.link(obj)
            obj.parent = parent
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_world = world
            obj["smg_zone"], obj["smg_row"] = self.zone, -1  # a new row of the new zone's table
            obj.pop("smg_dir", None)
            if rot is not None and before.rotation_difference(scene_io._zone_local(obj).decompose()[1]).angle < 1e-5:
                scene_io.remember_dir(obj, rot)  # both zones turned alike: the same angles
            moved += 1
        mark_dirty(context.scene)
        hint = core.ui.scenario_hint(context.scene, self.zone, "common")
        extra = f"; {skipped} an andere Objekte gehängt, nicht verschoben" if skipped else ""
        self.report({"WARNING"} if hint or skipped else {"INFO"}, f"{moved} nach {self.zone}{extra}{hint}")
        return {"FINISHED"}


def _ensure_layer(scene, zone_name, layer_name):
    """The zone's layer in the sidebar's list (a layer the zone did not have yet: shown, not in the scenario)."""
    zone = next((z for z in scene.mge_zones if z.name == zone_name), None)
    if zone is not None and layer_name not in {layer.name for layer in zone.layers}:
        entry = zone.layers.add()
        entry.name = layer_name
        entry.in_scenario = False
        entry["visible"] = True


class MGE_OT_set_field(bpy.types.Operator):
    bl_idname = "mge.set_field"
    bl_label = "Wert setzen"
    bl_options = {"REGISTER", "UNDO"}
    field: StringProperty()
    value: StringProperty()

    def execute(self, context):
        obj = context.active_object
        for target in [obj] + peers(context, obj, self.field):
            key = scene_io.PREFIX + self.field
            old = target.get(key)
            try:
                target[key] = type(old)(self.value) if old is not None else int(self.value)
            except ValueError:
                target[key] = self.value
        mark_dirty(context.scene)
        return {"FINISHED"}


class MGE_OT_copy_field(bpy.types.Operator):
    bl_idname = "mge.copy_field"
    bl_label = "Auf alle Gewählten"
    bl_description = ("Diesen Wert in alle gewählten Objekte übernehmen, die das Feld haben (Argumente nur bei "
                      "Objekten gleichen Namens: ihre Bedeutung hängt vom Objekt ab)")
    bl_options = {"REGISTER", "UNDO"}
    field: StringProperty()

    def execute(self, context):
        obj = context.active_object
        key = scene_io.PREFIX + self.field
        targets = peers(context, obj, self.field)
        for target in targets:
            target[key] = obj[key]
        mark_dirty(context.scene)
        self.report({"INFO"}, f"{self.field} = {obj[key]} in {len(targets) + 1} Objekten")
        return {"FINISHED"}


ARG_PREFIXES = ("Obj_arg", "path_arg")
OWN_FIELDS = {"name", "l_id"}  # never copied: what an object is, and its ID


def peers(context, obj, field):
    """The other selected objects a field's change goes to: those with the field (an argument only on
    objects of the same name)."""
    if context is None or field in OWN_FIELDS:
        return []
    key = scene_io.PREFIX + field
    name = obj.get(scene_io.PREFIX + "name")
    return [o for o in context.selected_objects if o is not obj and o.get("smg_kind") and key in o
            and (not field.startswith(ARG_PREFIXES) or o.get(scene_io.PREFIX + "name") == name)]


class MGE_OT_pick_value(bpy.types.Operator):
    bl_idname = "mge.pick_value"
    bl_label = "Wert wählen"
    bl_description = "Die bekannten Werte dieses Felds"
    field: StringProperty()

    def invoke(self, context, event):
        obj = context.active_object
        name = obj.get(scene_io.PREFIX + "name", "")
        values = editor().catalog(context.scene).parameter_values(name, self.field)
        field = self.field

        def draw(menu, _context):
            for value, notes in values:
                op = menu.layout.operator(MGE_OT_set_field.bl_idname, text=f"{value}: {notes}")
                op.field, op.value = field, str(value)
        context.window_manager.popup_menu(draw, title=self.field)
        return {"FINISHED"}


class MGE_OT_pick_path(bpy.types.Operator):
    bl_idname = "mge.pick_path"
    bl_label = "Pfad wählen"
    bl_description = "Einen Pfad der Zone wählen (setzt CommonPath_ID auf seine ID)"

    def invoke(self, context, event):
        obj = context.active_object
        zone = obj.get("smg_zone")
        root = galaxy_root(context.scene)
        paths = sorted((o for o in root.all_objects if o.get("smg_kind") == "path" and o.get("smg_zone") == zone),
                       key=lambda o: o.get(scene_io.PREFIX + "l_id", 0))

        def draw(menu, _context):
            op = menu.layout.operator(MGE_OT_set_field.bl_idname, text="Kein Pfad (-1)")
            op.field, op.value = "CommonPath_ID", "-1"
            for path in paths:
                ident = path.get(scene_io.PREFIX + "l_id")
                op = menu.layout.operator(MGE_OT_set_field.bl_idname, text=f"ID {ident}: {path.get(scene_io.PREFIX + 'name', '')}",
                                          icon="CURVE_BEZCURVE")
                op.field, op.value = "CommonPath_ID", str(ident)
        context.window_manager.popup_menu(draw, title=f"Pfade in {zone}")
        return {"FINISHED"}


def mark_dirty(scene):
    if scene.get("smg_galaxy"):
        scene["mge_dirty"] = True


def _field_row(layout, obj, field, cat, name, context=None):
    """A field: its name from the database (the raw field name in the tooltip row), a menu of its known
    values, the message's text for MessageId, a path chooser for CommonPath_ID."""
    key = scene_io.PREFIX + field
    info = cat.parameter(name, field)
    col = layout.column(align=True)
    row = col.row(align=True)
    others = peers(context, obj, field)
    mixed = any(o.get(key) != obj.get(key) for o in others)
    label = info[0] if info else field
    row.prop(obj, f'["{key}"]', text=f"{label}  (gemischt)" if mixed else label)
    if others:
        row.operator(MGE_OT_copy_field.bl_idname, text="", icon="COPYDOWN", depress=not mixed).field = field
    if cat.parameter_values(name, field):
        row.operator(MGE_OT_pick_value.bl_idname, text="", icon="DOWNARROW_HLT").field = field
    if field == "CommonPath_ID":
        row.operator(MGE_OT_pick_path.bl_idname, text="", icon="CURVE_BEZCURVE")
    if context is None:
        return
    hints = []
    if info:
        hints.append(field)
        if info[1]:
            hints.append(info[1])
    if field == "MessageId" and isinstance(obj.get(key), int) and obj.get(key) >= 0:
        text = editor().message_text(context.scene, obj.get("smg_zone", ""), name, obj.get(key))
        hints.append(f"Text: {text}" if text else "kein Text zu dieser Nummer")
    if hints:
        sub = col.column(align=True)
        sub.enabled = False
        _wrapped(sub, context, " · ".join(hints), 3)


def _wrapped(layout, context, text, lines=5):
    """text as lines that fit the sidebar's width (Blender cuts long labels in the middle)."""
    width = max(20, int((context.region.width - 30 * context.preferences.system.ui_scale) /
                        (6.5 * context.preferences.system.ui_scale)))
    col = layout.column(align=True)
    col.scale_y = 0.75
    for line in _wrap(text, width)[:lines]:
        col.label(text=line)


def _wrap(text, width):
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + ([line] if line else [])


def _fields(obj):
    return [k[len(scene_io.PREFIX):] for k in obj.keys() if k.startswith(scene_io.PREFIX)]


class _ObjectPanel:
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["props"]

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and bool(context.active_object.get("smg_kind"))


class MGE_PT_props(_ObjectPanel, bpy.types.Panel):
    bl_label = "Auswahl"

    def draw(self, context):
        obj, layout = context.active_object, self.layout
        kind = obj["smg_kind"]
        name = obj.get(scene_io.PREFIX + "name", obj.name)
        cat = editor().catalog(context.scene)
        entry = cat.entries.get(name)
        row = layout.row()
        picture = thumbs().icon(archive_name(name, scene_io.fields_of(obj)))
        if picture:
            row.template_icon(icon_value=picture, scale=4.0)
        col = row.column(align=True)
        col.label(text=entry["label"] if entry else name, icon=KIND_ICON.get(kind, "DOT"))
        col.label(text=f"{KIND_LABEL.get(kind, kind)} · {name}")
        ident = obj.get(scene_io.PREFIX + "l_id")
        col.label(text=f"ID {ident}" if isinstance(ident, int) and ident >= 0 else "ID beim Speichern")
        if kind != "stageobjinfo":
            col.operator_menu_enum(MGE_OT_move_zone.bl_idname, "zone", text=f"Zone {obj.get('smg_zone')}", icon="WORLD")
        if kind not in ("path", "stageobjinfo"):
            col.operator_menu_enum(MGE_OT_set_layer.bl_idname, "layer", text=layer_label(scene_io._layer_of(obj)),
                                   icon="RENDERLAYERS")
        if entry and entry.get("notes"):
            sub = layout.column()
            sub.enabled = False
            _wrapped(sub, context, entry["notes"])
        others = [o for o in context.selected_objects if o is not obj and o.get("smg_kind")]
        if others:
            box = layout.box()
            _wrapped(box, context, f"{len(others) + 1} gewählt: Zone und Ebene gelten für alle. Bei einem Feld "
                                   "übernimmt ↓ den Wert in alle, die es haben (Argumente: gleiche Objekte); "
                                   "„gemischt“: verschiedene Werte.", 6)
        layout.use_property_split = True
        layout.prop(obj, f'["{scene_io.PREFIX}name"]', text="Interner Name")
        if kind == "path" and obj.data.splines:
            spline = obj.data.splines[0]
            hint = layout.column()
            hint.enabled = False
            _wrapped(hint, context, f"{len(spline.bezier_points)} Punkte · bearbeiten mit Tab (Griffe = Kontrollpunkte)", 2)
            layout.prop(spline, "use_cyclic_u", text="Geschlossen")


class MGE_PT_props_place(_ObjectPanel, bpy.types.Panel):
    bl_label = "Lage im Spiel"
    bl_parent_id = "MGE_PT_props"

    @classmethod
    def poll(cls, context):
        return _ObjectPanel.poll(context) and context.active_object.get("smg_kind") != "path"

    def draw(self, context):
        obj, layout = context.active_object, self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(obj, "mge_game_pos", text="Position")
        layout.prop(obj, "mge_game_rot", text="Drehung °")
        layout.prop(obj, "mge_game_scale", text="Größe")
        hint = layout.column()
        hint.enabled = False
        _wrapped(hint, context, "Spieleinheiten in der Zone, Y zeigt nach oben", 2)


class MGE_PT_props_args(_ObjectPanel, bpy.types.Panel):
    bl_label = "Argumente"
    bl_parent_id = "MGE_PT_props"

    def draw(self, context):
        obj, layout = context.active_object, self.layout
        name = obj.get(scene_io.PREFIX + "name", "")
        cat = editor().catalog(context.scene)
        fields = _fields(obj)
        args = [f for f in fields if f.startswith(("Obj_arg", "path_arg"))]
        args.sort()
        known = [f for f in args if cat.parameter(name, f)]
        shown = known + [f for f in args if f not in known and obj.get(scene_io.PREFIX + f) not in (-1, None)]
        if obj["smg_kind"] == "planetobjinfo":
            for field in GRAVITY_FIELDS:
                if field in fields:
                    _field_row(layout, obj, field, cat, name, context)
        for field in sorted(shown, key=args.index):
            _field_row(layout, obj, field, cat, name, context)
        hidden = [f for f in args if f not in shown]
        if hidden:
            layout.prop(context.scene, "mge_show_all_args", text=f"Unbenutzte Argumente ({len(hidden)})",
                        icon="DOWNARROW_HLT" if context.scene.mge_show_all_args else "RIGHTARROW")
            if context.scene.mge_show_all_args:
                for field in hidden:
                    _field_row(layout, obj, field, cat, name, context)


class MGE_PT_props_switches(_ObjectPanel, bpy.types.Panel):
    bl_label = "Schalter"
    bl_parent_id = "MGE_PT_props"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        obj = context.active_object
        cat = editor().catalog(context.scene)
        name = obj.get(scene_io.PREFIX + "name", "")
        for field in sorted(f for f in _fields(obj) if f.startswith("SW_")):
            _field_row(self.layout, obj, field, cat, name, context)


class MGE_PT_props_links(_ObjectPanel, bpy.types.Panel):
    bl_label = "Verknüpfungen"
    bl_parent_id = "MGE_PT_props"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        obj = context.active_object
        cat = editor().catalog(context.scene)
        name = obj.get(scene_io.PREFIX + "name", "")
        for field in LINK_FIELDS:
            if field in _fields(obj):
                _field_row(self.layout, obj, field, cat, name, context)


def _point(obj, scene):
    """(points, index) of the path's chosen point (scene.mge_point, from 1), clamped."""
    spline = obj.data.splines[0] if obj.data.splines else None
    points = (spline.bezier_points if spline.type == "BEZIER" else spline.points) if spline else []
    return points, min(max(scene.mge_point, 1), max(len(points), 1)) - 1


def _get_point_args(scene):
    obj = bpy.context.active_object
    if obj is None or obj.get("smg_kind") != "path" or obj.mode != "OBJECT":
        return [-1] * 8
    points, index = _point(obj, scene)
    entries = scene_io.point_entries(obj)[1]
    known = entries[index] if index < len(entries) else None
    return [int(known["args"].get(f"point_arg{k}", -1)) if known else -1 for k in range(8)]


def _set_point_args(scene, value):
    obj = bpy.context.active_object
    if obj is None or obj.get("smg_kind") != "path" or obj.mode != "OBJECT":
        return
    points, index = _point(obj, scene)
    if not points:
        return
    stored, entries = scene_io.point_entries(obj)
    known = entries[index]
    if known is None:  # a point the path did not have when read: a record with its place and the args
        known = {"args": {}, "curve": scene_io.point_curve(points[index])}
        stored.append(known)
    known["args"] = {f"point_arg{k}": int(v) for k, v in enumerate(value)}
    obj["smg_points"] = json.dumps(stored)
    mark_dirty(scene)


class MGE_PT_props_points(_ObjectPanel, bpy.types.Panel):
    bl_label = "Punkte"
    bl_parent_id = "MGE_PT_props"

    @classmethod
    def poll(cls, context):
        return _ObjectPanel.poll(context) and context.active_object.get("smg_kind") == "path"

    def draw(self, context):
        obj, layout, scene = context.active_object, self.layout, context.scene
        if obj.mode != "OBJECT":
            hint = layout.column()
            hint.enabled = False
            _wrapped(hint, context, "Die Werte der Punkte im Objektmodus (Tab) bearbeiten", 2)
            return
        points, index = _point(obj, scene)
        row = layout.row(align=True)
        row.prop(scene, "mge_point", text=f"Punkt (von {len(points)})")
        layout.use_property_split = True
        layout.use_property_decorate = False
        col = layout.column(align=True)
        for k in range(8):
            col.prop(scene, "mge_point_args", index=k, text=f"point_arg{k}")
        hint = layout.column()
        hint.enabled = False
        _wrapped(hint, context, "Der gewählte Punkt ist im Viewport markiert. Was die Werte bedeuten, hängt vom "
                                "Objekt ab, das dem Pfad folgt (oft Tempo oder Wartezeit; -1 = Standard).", 3)


class MGE_PT_props_more(_ObjectPanel, bpy.types.Panel):
    bl_label = "Weitere Felder"
    bl_parent_id = "MGE_PT_props"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        obj = context.active_object
        cat = editor().catalog(context.scene)
        name = obj.get(scene_io.PREFIX + "name", "")
        rest = [f for f in _fields(obj) if f != "name" and not f.startswith(("Obj_arg", "path_arg", "SW_"))
                and f not in LINK_FIELDS and f not in GRAVITY_FIELDS]
        for field in sorted(rest):
            _field_row(self.layout, obj, field, cat, name, context)


class MGE_PT_props_play(_ObjectPanel, bpy.types.Panel):
    bl_label = "Speichern und Spielen"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context):
        core = editor()
        row = self.layout.row(align=True)
        row.operator(core.MGE_OT_save.bl_idname, text="Speichern", icon="FILE_TICK")
        row.operator(core.MGE_OT_preview.bl_idname, text="Testen", icon="RENDER_STILL")
        row.operator(core.MGE_OT_testplay.bl_idname, text="Testspielen", icon="PLAY")


# --- the tabs --------------------------------------------------------------------------------


def _check(layout, ok, text):
    layout.label(text=text, icon="CHECKMARK" if ok else "ERROR")


class MGE_PT_galaxy(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["galaxy"]
    bl_label = "Galaxie"

    def draw(self, context):
        scene, layout = context.scene, self.layout
        core = editor()
        if context.workspace is None or context.workspace.name != "Galaxie":
            layout.operator("mge.workspace", text="Galaxie-Arbeitsbereich öffnen", icon="WORKSPACE")
        if not scene.get("smg_galaxy"):
            box = layout.box()
            box.label(text="Willkommen im Galaxie-Editor", icon="WORLD")
            game = core.game_data(scene)
            _check(box, game.disc.exists(), "Spiel-Disc gefunden" if game.disc.exists() else f"Keine Disc in {game.disc}")
            from . import assets
            row = box.row()
            ready = not assets.stale()
            _check(row, ready, "Objekt-Palette bereit" if ready else "Objekt-Palette fehlt oder ist veraltet")
            if not ready:
                row.operator("mge.build_assets", text="Aufbauen")
            box.separator()
            _wrapped(box, context, "1  Galaxie wählen (Name im Spiel oder intern):", 2)
            box.prop(scene, "mge_galaxy", text="", icon="VIEWZOOM")
            big = box.row()
            big.scale_y = 1.6
            big.operator(core.MGE_OT_open.bl_idname, text="Galaxie öffnen", icon="FILE_FOLDER")
            hints = box.column(align=True)
            hints.enabled = False
            _wrapped(hints, context, "2  Objekte aus der Palette unten auf einen Planeten ziehen", 2)
            _wrapped(hints, context, "3  Spielen: automatisch testen oder testspielen", 2)
            return
        layout.label(text=core.galaxy_label(scene, scene["smg_galaxy"]), icon="WORLD_DATA")
        row = layout.row(align=True)
        row.prop(scene, "mge_galaxy", text="", icon="VIEWZOOM")
        row.operator(core.MGE_OT_open.bl_idname, text="Öffnen")
        row = layout.row(align=True)
        row.prop(scene, "mge_models", text="Modelle", icon="SHADING_TEXTURE", toggle=True)
        row.operator("mge.view_start", text="Zum Start", icon="HOME")
        if scene.get("mge_dirty"):
            layout.label(text="Ungespeicherte Änderungen (⌘S speichert den Mod)", icon="RECORD_ON")


class MGE_PT_play(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["galaxy"]
    bl_label = "Spielen"
    bl_parent_id = "MGE_PT_galaxy"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def draw(self, context):
        scene, layout = context.scene, self.layout
        core = editor()
        row = layout.row(align=True)
        row.prop(scene, "mge_mod", text="Mod", icon="PACKAGE")
        on = core.mod_enabled(scene)
        if on is not None:
            row.operator("mge.mod_toggle", text="an" if on else "aus", icon="CHECKBOX_HLT" if on else "CHECKBOX_DEHLT",
                         depress=on)
        layout.operator(core.MGE_OT_save.bl_idname, text="Speichern  (⌘S)", icon="FILE_TICK")
        test = layout.column(align=True)
        test.operator(core.MGE_OT_preview.bl_idname, text="Automatisch testen (Bilder)", icon="RENDER_STILL")
        test.prop(scene, "mge_warp", text="Test beginnt am Vorschau-Start")
        big = layout.row()
        big.scale_y = 1.5
        big.operator(core.MGE_OT_testplay.bl_idname, text="Testspielen", icon="PLAY")
        layout.operator(core.MGE_OT_play.bl_idname, text="Im ganzen Spiel spielen", icon="WORLD")
        hints = layout.column(align=True)
        hints.enabled = False
        _wrapped(hints, context, "Automatisch testen: das Spiel läuft unsichtbar, Mario läuft los, du bekommst Bilder. "
                                 "Testspielen: nur diese Galaxie im Testbed, ohne Titel und Spielstand; nach jedem "
                                 "Speichern lädt es neu. Im ganzen Spiel: einen Spielstand laden, dann geht es hierher. "
                                 "Deine Disc bleibt unverändert; der Mod liegt daneben.", 8)
        if scene.mge_status:
            layout.label(text=scene.mge_status, icon="INFO")


class MGE_PT_scenarios(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["galaxy"]
    bl_label = "Szenarien"
    bl_parent_id = "MGE_PT_galaxy"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def draw(self, context):
        self.layout.column(align=True).prop(context.scene, "mge_scenario", expand=True)


class MGE_PT_zones(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["galaxy"]
    bl_label = "Zonen und Ebenen"
    bl_parent_id = "MGE_PT_galaxy"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def draw(self, context):
        scene, layout = context.scene, self.layout
        layout.template_list("MGE_UL_zones", "", scene, "mge_zones", scene, "mge_zone_index", rows=4)
        if 0 <= scene.mge_zone_index < len(scene.mge_zones):
            zone = scene.mge_zones[scene.mge_zone_index]
            layout.label(text=f"Ebenen von {zone.name}  (✓ im Szenario)")
            layout.template_list("MGE_UL_layers", "", zone, "layers", zone, "layer_index", rows=3)
        row = layout.row(align=True)
        row.operator(MGE_OT_zones_all.bl_idname, text="Alles zeigen", icon="HIDE_OFF").mode = "ALL"
        row.operator(MGE_OT_zones_all.bl_idname, text="Wie im Szenario", icon="FILE_REFRESH").mode = "SCENARIO"


class MGE_PT_show(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["galaxy"]
    bl_label = "Anzeigen"
    bl_parent_id = "MGE_PT_galaxy"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def draw(self, context):
        grid = self.layout.grid_flow(columns=2, even_columns=True, align=True)
        for key, label, icon in GROUP_LABELS:
            swatch = swatch_icon(key)
            if swatch:
                grid.prop(context.scene, f"mge_show_{key}", text=label, icon_value=swatch, toggle=True)
            else:
                grid.prop(context.scene, f"mge_show_{key}", text=label, icon=icon, toggle=True)
        self.layout.prop(context.scene, "mge_line_width", text="Linienstärke", slider=True)


class MGE_PT_objects(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["galaxy"]
    bl_label = "Objektliste"
    bl_parent_id = "MGE_PT_galaxy"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def draw(self, context):
        scene, layout = context.scene, self.layout
        layout.prop(scene, "mge_object_search", text="", icon="VIEWZOOM")
        row = layout.row(align=True)
        row.prop(scene, "mge_browse_group", text="")
        row.prop(scene, "mge_browse_zone", text="")
        layout.template_list("MGE_UL_objects", "", bpy.data, "objects", scene, "mge_object_index", rows=10)
        layout.operator(MGE_OT_frame.bl_idname, icon="ZOOM_SELECTED")


class MGE_OT_fill_catalog(bpy.types.Operator):
    bl_idname = "mge.fill_catalog"
    bl_label = "Katalog laden"

    def execute(self, context):
        fill_catalog(context)
        return {"FINISHED"}


def swatch_icon(group):
    """A small colour swatch per drawn kind (the viewport's colours), as preview icons."""
    kind = GROUP_COLOUR.get(group)
    if kind is None:
        return 0
    previews = thumbs().previews
    key = f"swatch:{group}"
    if key not in previews:
        icon = previews.new(key)
        size = 32
        icon.icon_size = (size, size)
        r, g, b, _ = scene_io.COLORS.get(kind, (0.7, 0.7, 0.7, 1))
        pixels = []
        for y in range(size):
            for x in range(size):
                inside = 6 <= x < size - 6 and 6 <= y < size - 6
                pixels += [r, g, b, 1.0] if inside else [0.0, 0.0, 0.0, 0.0]
        icon.icon_pixels_float = pixels
    return previews[key].icon_id


CLASSES = (MGE_Layer, MGE_Zone, MGE_CatalogItem, MGE_UL_zones, MGE_UL_layers, MGE_UL_objects, MGE_UL_catalog,
           MGE_OT_zones_all, MGE_OT_zone_solo, MGE_OT_frame, MGE_OT_place, MGE_OT_build_assets, MGE_OT_thumbnails,
           MGE_OT_set_layer, MGE_OT_move_zone, MGE_OT_set_field, MGE_OT_copy_field, MGE_OT_pick_value, MGE_OT_pick_path,
           MGE_OT_fill_catalog,
           MGE_PT_galaxy, MGE_PT_scenarios, MGE_PT_zones, MGE_PT_play, MGE_PT_show, MGE_PT_objects,
           MGE_PT_props, MGE_PT_props_place, MGE_PT_props_args, MGE_PT_props_switches, MGE_PT_props_links,
           MGE_PT_props_points, MGE_PT_props_more, MGE_PT_props_play)
_owner = object()


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    scene = bpy.types.Scene
    scene.mge_zones = CollectionProperty(type=MGE_Zone)
    scene.mge_zone_index = IntProperty()
    for key, label, _ in GROUP_LABELS:
        setattr(scene, f"mge_show_{key}", BoolProperty(name=label, default=key not in ("other", "zones", "cameras", "sky"),
                                                       update=lambda self, context: apply_visibility(context.scene)))
    scene.mge_object_index = IntProperty(update=_object_index_changed)
    scene.mge_browse_group = EnumProperty(name="Art", items=[("ALL", "Alle Arten", "")] +
                                          [(key, label, "") for key, label, _ in GROUP_LABELS])
    scene.mge_browse_zone = EnumProperty(name="Zone", items=_browse_zones)
    scene.mge_show_all_args = BoolProperty(default=False)
    scene.mge_object_search = StringProperty(name="Suchen", description="Name im Spiel oder interner Name",
                                             options={"TEXTEDIT_UPDATE"})
    scene.mge_point = IntProperty(name="Punkt", default=1, min=1, description="Der Pfadpunkt, dessen Werte unten stehen")
    scene.mge_point_args = IntVectorProperty(name="point_arg", size=8, get=_get_point_args, set=_set_point_args)
    wm = bpy.types.WindowManager
    wm.mge_catalog = CollectionProperty(type=MGE_CatalogItem)
    wm.mge_catalog_index = IntProperty(update=_catalog_chosen)
    wm.mge_catalog_filter = EnumProperty(name="Art", items=_categories)
    obj = bpy.types.Object
    obj.mge_game_pos = FloatVectorProperty(size=3, get=_get_transform("pos"), set=_set_transform("pos"), precision=1,
                                           step=1000, subtype="XYZ")
    obj.mge_game_rot = FloatVectorProperty(size=3, get=_get_transform("rot"), set=_set_transform("rot"), precision=2,
                                           subtype="XYZ")
    obj.mge_game_scale = FloatVectorProperty(size=3, get=_get_transform("scale"), set=_set_transform("scale"),
                                             precision=3, subtype="XYZ")
    bpy.msgbus.subscribe_rna(key=(bpy.types.LayerObjects, "active"), owner=_owner, args=(), notify=_active_changed)


def unregister():
    bpy.msgbus.clear_by_owner(_owner)
    if _state["thumbs"] is not None:
        _state["thumbs"].close()
        _state["thumbs"] = None
    for name in ("mge_game_pos", "mge_game_rot", "mge_game_scale"):
        delattr(bpy.types.Object, name)
    for name in ("mge_catalog", "mge_catalog_index", "mge_catalog_filter"):
        delattr(bpy.types.WindowManager, name)
    for name in ["mge_zones", "mge_zone_index", "mge_object_index", "mge_browse_group", "mge_browse_zone",
                 "mge_show_all_args", "mge_object_search", "mge_point", "mge_point_args"] + [f"mge_show_{key}" for key, _, _ in GROUP_LABELS]:
        delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

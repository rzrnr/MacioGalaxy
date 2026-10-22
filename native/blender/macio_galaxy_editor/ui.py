"""The editor's own interface: four sidebar tabs in the 3D view (N), laid out like Whitehole's.

- Galaxie: open a galaxy, its scenarios (each shows the layers it uses), the zones with an eye each and
  the selected zone's layers, and switches for what is drawn (objects, map parts, areas, cameras,
  gravity, start points, paths, zone placements, other).
- Objekte: every placed object in a list (search, filter by kind and zone; a click selects it), and
  the catalog of the game's objects with preview pictures, to place one at the 3D cursor.
- Eigenschaften: the selected object: picture, description, place in the game's coordinates, and its
  fields in groups (arguments with what they mean, gravity, switches, links, the rest).
- Spiel: save as a mod, play headless or in the game.
"""
import sys

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatVectorProperty, IntProperty,
                       PointerProperty, StringProperty)

from . import scene_io
from .catalog import KIND_LABEL
from .convert import basis_from_game, game_from_basis
from .galaxy import LAYERS
from .models import archive_name
from .thumbnails import Thumbnails

TAB = {"galaxy": "Galaxie", "objects": "Objekte", "props": "Eigenschaften", "game": "Spiel"}
GROUP_LABELS = [("objects", "Objekte", "OBJECT_DATA"), ("mapparts", "Map-Teile", "MESH_CUBE"),
                ("areas", "Areas", "CUBE"), ("cameras", "Kameras", "CAMERA_DATA"), ("gravity", "Gravity", "FORCE_FORCE"),
                ("starts", "Startpunkte", "ARMATURE_DATA"), ("paths", "Paths", "CURVE_BEZCURVE"),
                ("zones", "Zonen", "EMPTY_AXIS"), ("other", "Sonstiges", "SOUND")]
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


class MGE_UL_layers(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_property, index=0, flt_flag=0):
        row = layout.row(align=True)
        row.prop(item, "visible", text="", emboss=False, icon="HIDE_OFF" if item.visible else "HIDE_ON")
        name = "Gemeinsam (common)" if item.name == "common" else f"Ebene {item.name[-1].upper()} ({item.name})"
        row.label(text=name, icon="CHECKMARK" if item.in_scenario else "BLANK1")


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
        split = row.split(factor=0.66, align=True)
        split.label(text=f"{shown} · {name}" if shown else name)
        zone = item.get("smg_zone", "")
        for ending in ("Galaxy", "Zone"):
            zone = zone[:-len(ending)] if zone.endswith(ending) and len(zone) > len(ending) else zone
        layer = scene_io._layer_of(item)
        where = "Path" if kind == "path" else ("" if layer == "common" else f" · {layer[-1].upper()}")
        split.label(text=f"{zone}{where}")

    def filter_items(self, context, data, propname):
        scene = context.scene
        objects = getattr(data, propname)
        root = galaxy_root(scene)
        members = set(root.all_objects) if root else set()
        kinds = scene_io.GROUPS.get(scene.mge_browse_group)
        zone = scene.mge_browse_zone
        text = self.filter_name.lower()
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


def _get_transform(part):
    def get(obj):
        if not obj.get("smg_kind") or obj.get("smg_kind") == "path":
            return (0.0, 0.0, 0.0)
        pos, rot, scale = game_from_basis(scene_io._zone_local(obj))
        return {"pos": pos, "rot": rot, "scale": scale}[part]
    return get


def _set_transform(part):
    def set_(obj, value):
        if not obj.get("smg_kind") or obj.get("smg_kind") == "path":
            return
        pos, rot, scale = game_from_basis(scene_io._zone_local(obj))
        values = {"pos": pos, "rot": rot, "scale": scale}
        values[part] = list(value)
        scene_io.set_zone_local(obj, basis_from_game(values["pos"], values["rot"], values["scale"]))
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
    bl_description = "Das Objekt in eine andere Ebene seiner Zone legen"
    bl_options = {"REGISTER", "UNDO"}
    layer: EnumProperty(items=_layers_of_zone)

    def execute(self, context):
        obj = context.active_object
        root = galaxy_root(context.scene)
        target = scene_io.layer_collection(root, obj["smg_zone"], self.layer)
        for coll in list(obj.users_collection):
            coll.objects.unlink(obj)
        target.objects.link(obj)
        zone = next((z for z in context.scene.mge_zones if z.name == obj["smg_zone"]), None)
        if zone is not None and self.layer not in {layer.name for layer in zone.layers}:
            entry = zone.layers.add()
            entry.name = self.layer
        return {"FINISHED"}


def _field_row(layout, obj, field, cat, name, context=None):
    key = scene_io.PREFIX + field
    info = cat.parameter(name, field)
    col = layout.column(align=True)
    col.prop(obj, f'["{key}"]', text=f"{info[0]}  ({field})" if info else field)
    if info and (info[1] or info[2]) and context is not None:
        _wrapped(col, context, " · ".join(x for x in (info[1], info[2]) if x), 3)


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
        picture = thumbs().icon(archive_name(name, scene_io.fields_of(obj))) if kind in scene_io.MODEL_KINDS else 0
        if picture:
            row.template_icon(icon_value=picture, scale=4.0)
        col = row.column(align=True)
        col.label(text=entry["label"] if entry else name, icon=KIND_ICON.get(kind, "DOT"))
        col.label(text=f"{KIND_LABEL.get(kind, kind)} · {name}")
        col.label(text=f"Zone {obj.get('smg_zone')}")
        if kind != "path":
            col.operator_menu_enum(MGE_OT_set_layer.bl_idname, "layer",
                                   text=f"Ebene: {scene_io._layer_of(obj)}", icon="RENDERLAYERS")
        if entry and entry.get("notes"):
            _wrapped(layout, context, entry["notes"])
        layout.prop(obj, f'["{scene_io.PREFIX}name"]', text="Name")
        if kind == "path":
            layout.label(text=f"{len(obj.data.splines[0].bezier_points) if obj.data.splines else 0} Punkte; "
                              "bearbeiten mit Tab", icon="INFO")
            if obj.data.splines:
                layout.prop(obj.data.splines[0], "use_cyclic_u", text="Geschlossen")


class MGE_PT_props_place(_ObjectPanel, bpy.types.Panel):
    bl_label = "Lage im Spiel"
    bl_parent_id = "MGE_PT_props"

    @classmethod
    def poll(cls, context):
        return _ObjectPanel.poll(context) and context.active_object.get("smg_kind") != "path"

    def draw(self, context):
        obj, col = context.active_object, self.layout.column(align=True)
        for prop, label in (("mge_game_pos", "Position"), ("mge_game_rot", "Drehung °"), ("mge_game_scale", "Größe")):
            col.label(text=label)
            col.row(align=True).prop(obj, prop, text="")
        self.layout.label(text="Spieleinheiten, Y oben, in der Zone", icon="INFO")


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


# --- the tabs --------------------------------------------------------------------------------


class MGE_PT_galaxy(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["galaxy"]
    bl_label = "Galaxie"

    def draw(self, context):
        scene, layout = context.scene, self.layout
        core = editor()
        row = layout.row(align=True)
        row.prop(scene, "mge_galaxy", text="", icon="WORLD")
        row.operator(core.MGE_OT_open.bl_idname, text="", icon="FILE_FOLDER")
        if not scene.get("smg_galaxy"):
            layout.label(text="Galaxie wählen und öffnen", icon="INFO")
            return
        layout.label(text=core.galaxy_label(scene, scene["smg_galaxy"]), icon="WORLD_DATA")
        layout.prop(scene, "mge_models", text="Modelle des Spiels", icon="SHADING_TEXTURE")


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
            grid.prop(context.scene, f"mge_show_{key}", text=label, icon=icon, toggle=True)


class MGE_PT_objects(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["objects"]
    bl_label = "In der Galaxie"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def draw(self, context):
        scene, layout = context.scene, self.layout
        row = layout.row(align=True)
        row.prop(scene, "mge_browse_group", text="")
        row.prop(scene, "mge_browse_zone", text="")
        layout.template_list("MGE_UL_objects", "", bpy.data, "objects", scene, "mge_object_index", rows=10)
        layout.operator(MGE_OT_frame.bl_idname, icon="ZOOM_SELECTED")


class MGE_PT_catalog(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["objects"]
    bl_label = "Neues Objekt"

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy"))

    def draw(self, context):
        wm, layout = context.window_manager, self.layout
        if not len(wm.mge_catalog):
            layout.operator("mge.fill_catalog", icon="FILE_REFRESH")
            return
        layout.prop(wm, "mge_catalog_filter", text="")
        layout.template_list("MGE_UL_catalog", "", wm, "mge_catalog", wm, "mge_catalog_index", rows=8)
        if 0 <= wm.mge_catalog_index < len(wm.mge_catalog):
            item = wm.mge_catalog[wm.mge_catalog_index]
            row = layout.row()
            picture = thumbs().icon(item.archive)
            if picture:
                row.template_icon(icon_value=picture, scale=5.0)
            col = row.column(align=True)
            col.label(text=item.label)
            col.label(text=f"{KIND_LABEL.get(item.kind, item.kind)} · {item.name}")
            if item.category:
                col.label(text=item.category)
            _wrapped(layout, context, item.notes, 4)
            layout.operator(MGE_OT_place.bl_idname, icon="ADD")
        layout.operator(editor().MGE_OT_add_path.bl_idname, icon="CURVE_BEZCURVE")
        row = layout.row()
        row.operator(MGE_OT_thumbnails.bl_idname, icon="IMAGE_DATA")
        layout.label(text="Ziel: aktive Ebene im Outliner, sonst die des gewählten Objekts", icon="INFO")


class MGE_OT_fill_catalog(bpy.types.Operator):
    bl_idname = "mge.fill_catalog"
    bl_label = "Katalog laden"

    def execute(self, context):
        fill_catalog(context)
        return {"FINISHED"}


class MGE_PT_game(bpy.types.Panel):
    bl_space_type, bl_region_type, bl_category = "VIEW_3D", "UI", TAB["game"]
    bl_label = "Spiel"

    def draw(self, context):
        scene, layout = context.scene, self.layout
        core = editor()
        layout.prop(scene, "mge_mod", text="Mod")
        layout.operator(core.MGE_OT_save.bl_idname, icon="FILE_TICK")
        row = layout.row(align=True)
        row.operator(core.MGE_OT_preview.bl_idname, icon="RENDER_STILL")
        row.prop(scene, "mge_warp", text="", icon="PIVOT_CURSOR")
        layout.operator(core.MGE_OT_play.bl_idname, icon="PLAY")
        if scene.mge_status:
            layout.label(text=scene.mge_status, icon="INFO")
        layout.separator()
        layout.prop(scene, "mge_user", text="Spielordner")


CLASSES = (MGE_Layer, MGE_Zone, MGE_CatalogItem, MGE_UL_zones, MGE_UL_layers, MGE_UL_objects, MGE_UL_catalog,
           MGE_OT_zones_all, MGE_OT_frame, MGE_OT_place, MGE_OT_thumbnails, MGE_OT_set_layer, MGE_OT_fill_catalog,
           MGE_PT_galaxy, MGE_PT_scenarios, MGE_PT_zones, MGE_PT_show,
           MGE_PT_objects, MGE_PT_catalog,
           MGE_PT_props, MGE_PT_props_place, MGE_PT_props_args, MGE_PT_props_switches, MGE_PT_props_links,
           MGE_PT_props_more, MGE_PT_game)
_owner = object()


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    scene = bpy.types.Scene
    scene.mge_zones = CollectionProperty(type=MGE_Zone)
    scene.mge_zone_index = IntProperty()
    for key, label, _ in GROUP_LABELS:
        setattr(scene, f"mge_show_{key}", BoolProperty(name=label, default=key not in ("other", "zones"),
                                                       update=lambda self, context: apply_visibility(context.scene)))
    scene.mge_object_index = IntProperty(update=_object_index_changed)
    scene.mge_browse_group = EnumProperty(name="Art", items=[("ALL", "Alle Arten", "")] +
                                          [(key, label, "") for key, label, _ in GROUP_LABELS])
    scene.mge_browse_zone = EnumProperty(name="Zone", items=_browse_zones)
    scene.mge_show_all_args = BoolProperty(default=False)
    wm = bpy.types.WindowManager
    wm.mge_catalog = CollectionProperty(type=MGE_CatalogItem)
    wm.mge_catalog_index = IntProperty()
    wm.mge_catalog_filter = EnumProperty(name="Art", items=_categories)
    obj = bpy.types.Object
    obj.mge_game_pos = FloatVectorProperty(size=3, get=_get_transform("pos"), set=_set_transform("pos"), precision=1,
                                           step=1000)
    obj.mge_game_rot = FloatVectorProperty(size=3, get=_get_transform("rot"), set=_set_transform("rot"), precision=2)
    obj.mge_game_scale = FloatVectorProperty(size=3, get=_get_transform("scale"), set=_set_transform("scale"),
                                             precision=3)
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
                 "mge_show_all_args"] + [f"mge_show_{key}" for key, _, _ in GROUP_LABELS]:
        delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

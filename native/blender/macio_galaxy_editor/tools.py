"""The editor's tools in the 3D view's toolbar (left, T), with their own icons.

- Setzen: a click on a surface places the chosen object there, standing on it (its up axis, game +Y,
  along the surface normal), at the chosen height, in the clicked object's zone and layer; a click on a
  small placed object selects it instead (Ctrl+click places anyway); a click into empty space places
  nothing.
- Pfad: clicks add points (a little above the surface; straight segments unless "Kurven"); Enter or a
  right click finishes, Esc drops it. The path gets its ID at once (for CommonPath_ID).
- Schwerkraft: a click on a planet places the chosen gravity at the middle of its bounds with a Range
  reaching past the clicked point, in the planet's zone and layer; elsewhere at the click.
- Teststart: a click sets where Mario starts in Testspielen and the automatic test (the 3D cursor, mge_warp on).

The tool's options are in the tool header (the object to place, the height of path points, ...).
Icons are drawn here as triangles in Blender's icon format (.dat: "VCO\\0", size, offset, then
x,y bytes per corner and RGBA bytes per corner) into ~/Library/Caches/MacioGalaxyEditor/icons.
"""
import math
import struct
import sys
from pathlib import Path

import bpy
from bpy.props import EnumProperty, FloatProperty
from bpy_extras import view3d_utils
from mathutils import Matrix, Vector

from . import scene_io
from .assets import aligned_matrix
from .convert import to_game
from .galaxy import PathPoint, Path_

ICONS = Path.home() / "Library/Caches/MacioGalaxyEditor/icons"
LIGHT, HAZEL, DARK = (225, 225, 225, 255), (200, 140, 80, 255), (90, 60, 35, 255)
GRAVITY_TYPES = [("GlobalPointGravity", "Planet (Punkt)", "Zieht zum Mittelpunkt (Kugelplaneten)"),
                 ("GlobalPlaneGravityInBox", "Ebene im Quader", "Zieht nach unten, innerhalb eines Quaders"),
                 ("GlobalPlaneGravityInCylinder", "Ebene im Zylinder", "Zieht nach unten, innerhalb eines Zylinders"),
                 ("GlobalCubeGravity", "Würfel", "Zieht zu einem Quader hin (würfelförmige Planeten)"),
                 ("GlobalSegmentGravity", "Strecke", "Zieht zu einer Linie hin (Stäbe, Röhren)"),
                 ("GlobalDiskGravity", "Scheibe", "Zieht zu einer Scheibe hin"),
                 ("GlobalPlaneGravity", "Ebene (Kugelbereich)", "Zieht nach unten, innerhalb einer Kugel")]


def editor():
    return sys.modules[__package__]


# --- icons -----------------------------------------------------------------------------------


def _write_icon(name, triangles):
    """triangles: [((x, y), (x, y), (x, y), rgba)] with x, y in 0..1 (y up)."""
    ICONS.mkdir(parents=True, exist_ok=True)
    coords, colors = bytearray(), bytearray()
    for a, b, c, rgba in triangles:
        for x, y in (a, b, c):
            coords += bytes((max(0, min(255, round(x * 255))), max(0, min(255, round(y * 255)))))
            colors += bytes(rgba)
    (ICONS / f"{name}.dat").write_bytes(b"VCO\0" + bytes((255, 255, 0, 0)) + bytes(coords) + bytes(colors))
    return str(ICONS / name)


def _fan(center, points, rgba):
    return [(center, points[i], points[(i + 1) % len(points)], rgba) for i in range(len(points))]


def _circle(cx, cy, r, rgba, n=24):
    return _fan((cx, cy), [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)],
                rgba)


def _star(cx, cy, outer, inner, rgba, rotation=math.pi / 2):
    points = [(cx + (outer if i % 2 == 0 else inner) * math.cos(rotation + math.pi * i / 5),
               cy + (outer if i % 2 == 0 else inner) * math.sin(rotation + math.pi * i / 5)) for i in range(10)]
    return _fan((cx, cy), points, rgba)


def _line(a, b, width, rgba):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1
    nx, ny = -dy / length * width / 2, dx / length * width / 2
    p = [(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)]
    return [(p[0], p[1], p[2], rgba), (p[0], p[2], p[3], rgba)]


def make_icons():
    icons = {}
    # Setzen: a star standing on a planet's curve.
    tris = _circle(0.5, -0.55, 0.85, DARK, 48)
    tris += _star(0.5, 0.58, 0.36, 0.15, HAZEL)
    tris += _line((0.5, 0.22), (0.5, 0.3), 0.04, LIGHT)
    icons["place"] = _write_icon("ops.mge.place", tris)
    # Path: a curve of dots.
    tris = []
    for i in range(7):
        t = i / 6
        x, y = 0.12 + 0.76 * t, 0.5 + 0.28 * math.sin(t * 2 * math.pi)
        tris += _circle(x, y, 0.07 if i in (0, 6) else 0.05, HAZEL if i in (0, 6) else LIGHT, 12)
    icons["path"] = _write_icon("ops.mge.path", tris)
    # Gravity: a planet with arrows pointing at it.
    tris = _circle(0.5, 0.5, 0.2, HAZEL, 32)
    for k in range(4):
        a = math.pi / 4 + k * math.pi / 2
        far, near = (0.5 + 0.44 * math.cos(a), 0.5 + 0.44 * math.sin(a)), (0.5 + 0.27 * math.cos(a), 0.5 + 0.27 * math.sin(a))
        tris += _line(far, near, 0.06, LIGHT)
        side = (math.cos(a + math.pi / 2) * 0.06, math.sin(a + math.pi / 2) * 0.06)
        tip_back = (0.5 + 0.33 * math.cos(a), 0.5 + 0.33 * math.sin(a))
        tris.append((near, (tip_back[0] + side[0], tip_back[1] + side[1]), (tip_back[0] - side[0], tip_back[1] - side[1]), LIGHT))
    icons["gravity"] = _write_icon("ops.mge.gravity", tris)
    # Mario-Start: a flag on a pole.
    tris = _line((0.3, 0.1), (0.3, 0.9), 0.07, LIGHT)
    tris += [((0.33, 0.9), (0.85, 0.75), (0.33, 0.58), HAZEL)]
    tris += _circle(0.3, 0.1, 0.09, LIGHT, 16)
    icons["start"] = _write_icon("ops.mge.start", tris)
    return icons


# --- picking ---------------------------------------------------------------------------------


def pick(context, event):
    """(location, normal, object) under the mouse in the 3D view, or (cursor-depth point, None, None)."""
    region, view = context.region, context.region_data
    coord = (event.mouse_region_x, event.mouse_region_y)
    origin = view3d_utils.region_2d_to_origin_3d(region, view, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, view, coord)
    hit, location, normal, _, obj, _ = context.scene.ray_cast(context.evaluated_depsgraph_get(), origin, direction)
    if hit:
        return location, normal, obj
    return view3d_utils.region_2d_to_location_3d(region, view, coord, context.scene.cursor.location), None, None


def _placed_root(obj):
    """The galaxy object a hit belongs to (hits land on evaluated copies)."""
    obj = getattr(obj, "original", obj)
    return obj if obj is not None and obj.get("smg_kind") else None


SMALL = 3.0  # metres: a hit object smaller than this is something placed, not ground to place on


def _size(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return max((a - b).length for a in corners for b in corners)


def _bounds_centre(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return sum(corners, Vector()) / 8


def _target_of(context, hit):
    """(collection, zone) new things go to: the clicked galaxy object's layer, else the active layer."""
    core = editor()
    if hit is not None and hit.get("smg_kind") and hit.get("smg_kind") != "stageobjinfo":
        root = bpy.data.collections.get(f"SMG {context.scene['smg_galaxy']}")
        collection = scene_io.layer_collection(root, hit["smg_zone"], scene_io._layer_of(hit))
        return collection, hit["smg_zone"]
    collection = core._target_collection(context)
    return collection, collection["smg_zone"]


class MGE_OT_tool_click(bpy.types.Operator):
    bl_idname = "mge.tool_click"
    bl_label = "Klicken"
    bl_options = {"REGISTER", "UNDO"}
    mode: EnumProperty(items=[("PLACE", "Setzen", ""), ("GRAVITY", "Schwerkraft", ""), ("START", "Teststart", "")])
    force: bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and bool(context.scene.get("smg_galaxy"))

    def invoke(self, context, event):
        context.view_layer.update()
        wm, scene = context.window_manager, context.scene
        location, normal, hit = pick(context, event)
        hit = _placed_root(hit)
        if self.mode == "START":
            up = normal if normal is not None else Vector((0, 0, 1))
            scene.cursor.location = location + up * 0.5
            scene.mge_warp = True
            self.report({"INFO"}, f"Teststart gesetzt: Mario beginnt bei {tuple(round(v) for v in to_game(scene.cursor.location))} "
                                  "(Testspielen und automatischer Test)")
            return {"FINISHED"}
        if normal is None:
            self.report({"WARNING"}, "Kein Boden unter der Maus: auf einen Planeten oder ein Levelteil klicken")
            return {"CANCELLED"}
        if self.mode == "PLACE":
            if hit is not None and not self.force and hit.type == "MESH" and _size(hit) < SMALL:
                for other in context.selected_objects:
                    other.select_set(False)
                hit.select_set(True)
                context.view_layer.objects.active = hit
                self.report({"INFO"}, "Ausgewählt (Strg+Klick setzt trotzdem ein neues Objekt)")
                return {"FINISHED"}
            name = wm.mge_tool_object
            location = location + normal * scene.mge_tool_place_height * 0.01
            matrix = aligned_matrix(location, normal) if scene.mge_tool_align else Matrix.Translation(location)
            return self._add(context, name, matrix, target=_target_of(context, hit))
        name = wm.mge_tool_gravity
        values = {}
        matrix = Matrix.Translation(location)
        if name == "GlobalPointGravity" and hit is not None:
            centre = _bounds_centre(hit)
            matrix = Matrix.Translation(centre)
            values["Range"] = round((location - centre).length / 0.01 * 1.5)
        else:
            matrix = aligned_matrix(location, normal)
        return self._add(context, name, matrix, values, target=_target_of(context, hit))

    def _add(self, context, name, matrix, extra=None, target=None):
        return place(self, context, name, matrix, extra, target)


def place(op, context, name, matrix, extra=None, target=None):
    """Adds the catalog's object name at matrix (world) in target (collection, zone), selected; reports on op."""
    core = editor()
    cat = core.catalog(context.scene)
    entry = cat.entries.get(name)
    if entry is None:
        op.report({"WARNING"}, "Erst unten in der Palette oder im Werkzeugkopf ein Objekt wählen")
        return {"CANCELLED"}
    collection, zone = target or (core._target_collection(context), core._target_collection(context)["smg_zone"])
    parent = core._zone_parent(context, zone)
    local = parent.matrix_world.inverted() @ matrix if parent is not None else matrix
    values = dict(cat.defaults(name), **(extra or {}))
    obj = scene_io.new_object(name, entry["kind"], zone, values, local, collection, cat, parent=parent,
                              library=core.model_library(context.scene))
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    core.ui.mark_dirty(context.scene)
    hint = core.ui.scenario_hint(context.scene, zone, collection.get("smg_layer", "common"))
    op.report({"WARNING"} if hint else {"INFO"}, f"{entry['label']} gesetzt: {collection.name}{hint}")
    return {"FINISHED"}


def free_path_id(context, zone):
    """The next path ID of the zone (for CommonPath_ID, so a path has it before the first save)."""
    root = bpy.data.collections.get(f"SMG {context.scene['smg_galaxy']}")
    used = [o.get(scene_io.PREFIX + "l_id", -1) for o in root.all_objects
            if o.get("smg_kind") == "path" and o.get("smg_zone") == zone]
    return max([i for i in used if isinstance(i, int)] + [-1]) + 1


class MGE_OT_tool_path(bpy.types.Operator):
    """Clicks add path points; Enter or a right click finishes, Esc removes the path."""
    bl_idname = "mge.tool_path"
    bl_label = "Pfad zeichnen"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.area is not None and context.area.type == "VIEW_3D" and bool(context.scene.get("smg_galaxy"))

    def invoke(self, context, event):
        context.view_layer.update()
        core = editor()
        _, _, hit = pick(context, event)
        collection, self.zone = _target_of(context, _placed_root(hit))
        self.parent = core._zone_parent(context, self.zone)
        self.path_id = free_path_id(context, self.zone)
        self.points = []
        self.obj = None
        self._add_point(context, event)
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set("Pfad: Klick = Punkt · Enter oder Rechtsklick = fertig · Esc = verwerfen")
        return {"RUNNING_MODAL"}

    def _add_point(self, context, event):
        location, normal, _ = pick(context, event)
        up = normal if normal is not None else Vector((0, 0, 1))
        world = location + up * context.scene.mge_tool_path_height * 0.01
        local = self.parent.matrix_world.inverted() @ world if self.parent is not None else world
        game = to_game(local)
        self.points.append(PathPoint({f"pnt{i}_{a}": v for i in range(3) for a, v in zip("xyz", game)} |
                                     {f"point_arg{k}": -1 for k in range(8)}))
        if self.obj is not None:
            data = self.obj.data
            bpy.data.objects.remove(self.obj, do_unlink=True)
            bpy.data.curves.remove(data)
        values = {"name": f"Pfad {self.path_id}", "type": "Bezier", "closed": "OPEN", "l_id": self.path_id,
                  "usage": "General", "Path_ID": -1, **{f"path_arg{i}": -1 for i in range(8)}}
        collection = bpy.data.collections.get(scene_io.paths_collection_name(self.zone))
        self.obj = scene_io.make_path(Path_(self.zone, -1, values, list(self.points)), self.zone, collection, self.parent)
        handle = "AUTO" if context.scene.mge_tool_path_curved else "VECTOR"
        for bp in self.obj.data.splines[0].bezier_points:
            bp.handle_left_type = bp.handle_right_type = handle

    def modal(self, context, event):
        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self._add_point(context, event)
            return {"RUNNING_MODAL"}
        if event.type in ("RET", "NUMPAD_ENTER", "RIGHTMOUSE") and event.value == "PRESS":
            context.workspace.status_text_set(None)
            if len(self.points) < 2:
                self._drop()
                self.report({"WARNING"}, "Ein Pfad braucht mindestens zwei Punkte")
                return {"CANCELLED"}
            for other in context.selected_objects:
                other.select_set(False)
            self.obj.select_set(True)
            context.view_layer.objects.active = self.obj
            editor().ui.mark_dirty(context.scene)
            self.report({"INFO"}, f"Pfad {self.path_id} mit {len(self.points)} Punkten (für CommonPath_ID: {self.path_id})")
            bpy.ops.wm.call_menu(name=MGE_MT_path_use.bl_idname)
            return {"FINISHED"}
        if event.type == "ESC":
            context.workspace.status_text_set(None)
            self._drop()
            return {"CANCELLED"}
        return {"PASS_THROUGH"}

    def _drop(self):
        data = self.obj.data
        bpy.data.objects.remove(self.obj, do_unlink=True)
        bpy.data.curves.remove(data)


RAIL_OBJECTS = (("RailCoin", "Münzreihe", "Münzen entlang des Pfads"),
                ("PurpleRailCoin", "Lila Münzreihe", "Lila Münzen entlang des Pfads"))
COIN_SPACING = 100  # game units between the coins of a new coin line


class MGE_MT_path_use(bpy.types.Menu):
    bl_label = "Pfad benutzen für"
    bl_idname = "MGE_MT_path_use"

    def draw(self, context):
        layout = self.layout
        for name, label, _ in RAIL_OBJECTS:
            layout.operator(MGE_OT_path_use.bl_idname, text=label, icon="KEYTYPE_KEYFRAME_VEC").name = name
        layout.separator()
        layout.label(text="Nur Pfad (für Plattformen, Gegner, Kamera: im Objekt-Reiter bei CommonPath_ID)", icon="INFO")


class MGE_OT_path_use(bpy.types.Operator):
    """Puts an object that runs along the selected path at its start (CommonPath_ID = the path's ID)."""
    bl_idname = "mge.path_use"
    bl_label = "Objekt auf den Pfad"
    bl_description = "Ein Objekt an den Pfad hängen, das ihm folgt"
    bl_options = {"REGISTER", "UNDO"}
    name: EnumProperty(items=RAIL_OBJECTS)

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.get("smg_kind") == "path"

    def execute(self, context):
        core = editor()
        path = context.active_object
        points = [path.matrix_world @ p.co for p in path.data.splines[0].bezier_points]
        length = sum((a - b).length for a, b in zip(points, points[1:])) / 0.01
        count = max(2, min(64, round(length / COIN_SPACING) + 1))
        zone = path["smg_zone"]
        collection = core._target_collection(context)
        if collection.get("smg_zone") != zone:
            root = bpy.data.collections[f"SMG {context.scene['smg_galaxy']}"]
            collection = scene_io.layer_collection(root, zone, "common")
        if path.get(scene_io.PREFIX + "l_id", -1) < 0:
            path[scene_io.PREFIX + "l_id"] = free_path_id(context, zone)
        extra = {"CommonPath_ID": path[scene_io.PREFIX + "l_id"], "Obj_arg0": count}
        return place(self, context, self.name, Matrix.Translation(points[0]), extra, (collection, zone))


# --- the tools -------------------------------------------------------------------------------


def _object_header(context, layout):
    wm, scene = context.window_manager, context.scene
    core = editor()
    entry = core.catalog(scene).entries.get(wm.mge_tool_object)
    picture = core.ui.thumbs().icon(core.models.archive_name(wm.mge_tool_object, core.catalog(scene).defaults(wm.mge_tool_object))) \
        if entry else 0
    if picture:
        layout.label(text=entry["label"], icon_value=picture)
    elif entry:
        layout.label(text=entry["label"], icon="OBJECT_DATA")
    layout.prop(wm, "mge_tool_object", text="", icon="VIEWZOOM")
    layout.prop(scene, "mge_tool_place_height", text="Höhe")
    layout.prop(scene, "mge_tool_align", text="Ausrichten")


class MGE_Tool_Place(bpy.types.WorkSpaceTool):
    bl_space_type, bl_context_mode = "VIEW_3D", "OBJECT"
    bl_idname = "mge.tool_place"
    bl_label = "Setzen"
    bl_description = "Klick auf eine Oberfläche setzt das gewählte Objekt dorthin, auf ihr stehend"
    bl_icon = "ops.generic.cursor"
    bl_keymap = (("mge.tool_click", {"type": "LEFTMOUSE", "value": "PRESS"}, {"properties": [("mode", "PLACE")]}),
                 ("mge.tool_click", {"type": "LEFTMOUSE", "value": "PRESS", "ctrl": True},
                  {"properties": [("mode", "PLACE"), ("force", True)]}),
                 ("mge.tool_click", {"type": "LEFTMOUSE", "value": "PRESS", "oskey": True},
                  {"properties": [("mode", "PLACE"), ("force", True)]}))

    def draw_settings(context, layout, tool):
        _object_header(context, layout)


class MGE_Tool_Path(bpy.types.WorkSpaceTool):
    bl_space_type, bl_context_mode = "VIEW_3D", "OBJECT"
    bl_idname = "mge.tool_path"
    bl_label = "Pfad zeichnen"
    bl_description = "Punkte auf Oberflächen klicken; Enter oder Rechtsklick beendet den Path"
    bl_icon = "ops.curve.draw"
    bl_keymap = (("mge.tool_path", {"type": "LEFTMOUSE", "value": "PRESS"}, None),)

    def draw_settings(context, layout, tool):
        layout.prop(context.scene, "mge_tool_path_height", text="Höhe über Boden")
        layout.prop(context.scene, "mge_tool_path_curved", text="Kurven")


class MGE_Tool_Gravity(bpy.types.WorkSpaceTool):
    bl_space_type, bl_context_mode = "VIEW_3D", "OBJECT"
    bl_idname = "mge.tool_gravity"
    bl_label = "Schwerkraft"
    bl_description = "Klick auf einen Planeten setzt die Schwerkraft in seine Mitte, mit passender Reichweite"
    bl_icon = "ops.mesh.primitive_sphere_add_gizmo"
    bl_keymap = (("mge.tool_click", {"type": "LEFTMOUSE", "value": "PRESS"}, {"properties": [("mode", "GRAVITY")]}),)

    def draw_settings(context, layout, tool):
        layout.prop(context.window_manager, "mge_tool_gravity", text="")


class MGE_Tool_Start(bpy.types.WorkSpaceTool):
    bl_space_type, bl_context_mode = "VIEW_3D", "OBJECT"
    bl_idname = "mge.tool_start"
    bl_label = "Teststart"
    bl_description = ("Klick setzt den Teststart: dort beginnt Mario beim Testspielen und beim automatischen Test "
                      "(der Startpunkt der Galaxie im Spiel bleibt)")
    bl_icon = "ops.generic.cursor"
    bl_keymap = (("mge.tool_click", {"type": "LEFTMOUSE", "value": "PRESS"}, {"properties": [("mode", "START")]}),)

    def draw_settings(context, layout, tool):
        layout.prop(context.scene, "mge_warp")


TOOLS = (MGE_Tool_Place, MGE_Tool_Path, MGE_Tool_Gravity, MGE_Tool_Start)


def _object_search(self, context, edit_text):
    return editor().catalog(context.scene).search(edit_text)


def register():
    icons = make_icons()
    for tool, key in zip(TOOLS, ("place", "path", "gravity", "start")):
        tool.bl_icon = icons[key]
    bpy.utils.register_class(MGE_OT_tool_click)
    bpy.utils.register_class(MGE_OT_tool_path)
    bpy.utils.register_class(MGE_OT_path_use)
    bpy.utils.register_class(MGE_MT_path_use)
    bpy.types.WindowManager.mge_tool_object = bpy.props.StringProperty(
        name="Objekt", default="Coin", search=_object_search, description="Was das Werkzeug Setzen setzt")
    bpy.types.WindowManager.mge_tool_gravity = EnumProperty(name="Gravity", items=GRAVITY_TYPES)
    bpy.types.Scene.mge_tool_align = bpy.props.BoolProperty(name="An Oberfläche ausrichten", default=True,
                                                            description="Das Objekt steht senkrecht auf der Oberfläche")
    bpy.types.Scene.mge_tool_place_height = FloatProperty(name="Höhe", default=0.0, soft_min=-500.0, soft_max=1000.0,
                                                          description="Spieleinheiten über der Oberfläche (Münzen schweben oft)")
    bpy.types.Scene.mge_tool_path_curved = bpy.props.BoolProperty(name="Kurven", default=False,
                                                                  description="Runde statt gerader Abschnitte")
    bpy.types.Scene.mge_tool_path_height = FloatProperty(name="Höhe über Boden", default=100.0, min=0.0, soft_max=2000.0,
                                                         description="Spieleinheiten über der Oberfläche")
    # After the cursor, as their own items: after "builtin.select_box" they'd join the select tools' group.
    bpy.utils.register_tool(MGE_Tool_Place, after={"builtin.cursor"}, separator=True, group=False)
    bpy.utils.register_tool(MGE_Tool_Path, after={MGE_Tool_Place.bl_idname})
    bpy.utils.register_tool(MGE_Tool_Gravity, after={MGE_Tool_Path.bl_idname})
    bpy.utils.register_tool(MGE_Tool_Start, after={MGE_Tool_Gravity.bl_idname})


def unregister():
    for tool in reversed(TOOLS):
        bpy.utils.unregister_tool(tool)
    for name in ("mge_tool_object", "mge_tool_gravity"):
        delattr(bpy.types.WindowManager, name)
    for name in ("mge_tool_align", "mge_tool_path_height", "mge_tool_place_height", "mge_tool_path_curved"):
        delattr(bpy.types.Scene, name)
    bpy.utils.unregister_class(MGE_MT_path_use)
    bpy.utils.unregister_class(MGE_OT_path_use)
    bpy.utils.unregister_class(MGE_OT_tool_path)
    bpy.utils.unregister_class(MGE_OT_tool_click)

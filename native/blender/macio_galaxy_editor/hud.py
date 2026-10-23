"""The viewport's HUD in the Galaxie workspace (gpu and blf in a POST_PIXEL draw handler), and the Q pie.

- Top left: the galaxy and scenario, where new things go (zone and layer), what the active tool does,
  and a hazelnut dot while there are unsaved changes.
- Bottom left: the legend of the wire shapes' colours, for the kinds that are shown.
- Without a galaxy: a card in the middle saying what to do first.
- Q (in this workspace only; elsewhere Blender's Quick Favorites): a pie with the editor's tools, the
  automatic test, saving, test play (the testbed) and playing in the whole game.
"""
import sys

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import scene_io

HAZEL = (0.541, 0.353, 0.196, 1.0)
PANEL = (0.05, 0.06, 0.11, 0.78)
TEXT = (0.92, 0.93, 0.96, 1.0)
DIM = (0.70, 0.72, 0.80, 1.0)
HINTS = {
    "mge.tool_place": "Klick: Objekt setzen  ·  Klick auf ein Objekt: auswählen  ·  Strg+Klick: trotzdem setzen",
    "mge.tool_path": "Klicks: Pfadpunkte  ·  Enter oder Rechtsklick: fertig  ·  Esc: verwerfen",
    "mge.tool_gravity": "Klick auf einen Planeten: Schwerkraft in seine Mitte",
    "mge.tool_start": "Klick: dort beginnt Mario beim automatischen Test",
}
DEFAULT_HINT = "Palette unten: Objekt anklicken oder auf einen Planeten ziehen  ·  Q: Werkzeuge"
LEGEND = [("objects", "Objekte", "objinfo"), ("mapparts", "Levelteile", "mappartsinfo"), ("areas", "Bereiche", "areaobjinfo"),
          ("cameras", "Kamerabereiche", "cameracubeinfo"), ("gravity", "Schwerkraft", "planetobjinfo"),
          ("starts", "Startpunkte", "startinfo"), ("paths", "Pfade", None)]
_handle = None


def editor():
    return sys.modules[__package__]


def _rect(x, y, w, h, colour):
    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    batch = batch_for_shader(shader, "TRIS", {"pos": [(x, y), (x + w, y), (x + w, y + h), (x, y), (x + w, y + h), (x, y + h)]})
    shader.uniform_float("color", colour)
    batch.draw(shader)


def _text(x, y, text, size, colour, scale):
    blf.size(0, size * scale)
    blf.color(0, *colour)
    blf.position(0, x, y, 0)
    blf.draw(0, text)
    return blf.dimensions(0, text)[0]


def _top_inset(area):
    """The height of the header and tool header drawn over the viewport (region overlap)."""
    return sum(r.height for r in area.regions if r.type in ("HEADER", "TOOL_HEADER") and r.height > 1 and r.alignment == "TOP")


def _bottom_inset(area):
    """The height of the asset shelf (the palette) drawn over the viewport's bottom."""
    return sum(r.height for r in area.regions if r.type in ("ASSET_SHELF", "ASSET_SHELF_HEADER") and r.height > 1
               and r.alignment == "BOTTOM")


def _left_edge(area):
    tools = next((r for r in area.regions if r.type == "TOOLS"), None)
    return (tools.width if tools is not None and tools.width > 1 else 0) + 12


def draw():
    context = bpy.context
    if context.workspace is None or context.workspace.name != "Galaxie" or context.region is None:
        return
    area, region, scene = context.area, context.region, context.scene
    scale = context.preferences.system.ui_scale
    gpu.state.blend_set("ALPHA")
    if not scene.get("smg_galaxy"):
        lines = [("Keine Galaxie geöffnet", 18, TEXT), ("Rechts im Reiter „Galaxie“ eine Galaxie wählen und öffnen", 13, DIM),
                 ("(N blendet die Seitenleiste ein)", 12, DIM)]
        width, height = 470 * scale, 104 * scale
        x, y = (region.width - width) / 2, (region.height - height) / 2
        _rect(x, y, width, height, PANEL)
        _rect(x, y + height - 4 * scale, width, 4 * scale, HAZEL)
        yy = y + height - 34 * scale
        for text, size, colour in lines:
            blf.size(0, size * scale)
            w = blf.dimensions(0, text)[0]
            _text(x + (width - w) / 2, yy, text, size, colour, scale)
            yy -= 26 * scale
        gpu.state.blend_set("NONE")
        return
    core = editor()
    galaxy = core.galaxy_label(scene, scene["smg_galaxy"])
    scenario = next((label for key, label, _ in core._scenarios(None, context) if key == scene.mge_scenario), "")
    try:
        target = core.target_name(context)
    except (KeyError, RuntimeError):
        target = ""
    if " · " in target:  # "Ebene A · Zone" -> "Zone › Ebene A"
        layer, zone = target.split(" · ", 1)
        target = f"{zone} › {layer}"
    tool = context.workspace.tools.from_space_view3d_mode("OBJECT", create=False)
    hint = HINTS.get(tool.idname if tool else "", DEFAULT_HINT)
    rows = [(galaxy, 14, TEXT), (scenario.split("   ·")[0], 12, DIM), (f"Neues landet in: Ebene des Planeten darunter, sonst {target}", 12, DIM), (hint, 12, DIM)]
    active = context.active_object
    if active is not None and active.select_get() and active.get("smg_kind"):
        rows.append((f"Ausgewählt: {active.name}  ·  G verschieben  ·  Shift+D kopieren  ·  X löschen", 12, DIM))
    if scene.mge_warp:
        rows.append(("Teststart an: Mario beginnt am Ring „Mario-Start (Test)“ (3D-Cursor)", 12, HAZEL))
    status = core.game_io.testbed_status_known()
    if status and (status.get("stage"), status.get("scenario")) == (scene["smg_galaxy"], scene.mge_scenario):
        rows.append(("▶ Testspiel läuft  ·  ⌘S oder F5 übernimmt die Änderungen", 12, TEXT))
    elif status:
        rows.append(("▶ Testspiel läuft mit anderem Szenario  ·  F5 wechselt", 12, TEXT))
    x = _left_edge(area)
    blf.size(0, 14 * scale)
    width = max(blf.dimensions(0, r[0])[0] if r[1] == 14 else 0 for r in rows)
    blf.size(0, 12 * scale)
    width = max([width + 110 * scale] + [blf.dimensions(0, r[0])[0] for r in rows if r[1] == 12]) + 28 * scale
    height = (len(rows) * 19 + 14) * scale
    y = region.height - _top_inset(area) - height - 10 * scale
    _rect(x, y, width, height, PANEL)
    _rect(x, y, 4 * scale, height, HAZEL)
    yy = y + height - 22 * scale
    for text, size, colour in rows:
        _text(x + 14 * scale, yy, text, size, colour, scale)
        yy -= 19 * scale
    if scene.get("mge_dirty"):
        blf.size(0, 11 * scale)
        w = blf.dimensions(0, "● ungespeichert")[0]
        _text(x + width - w - 12 * scale, y + height - 22 * scale, "● ungespeichert", 11, HAZEL, scale)
    if active is not None and active.get("smg_kind") == "path" and active.mode == "OBJECT":
        _point_marker(context, active, scale)
    if scene.mge_warp:
        _start_marker(context, scale)
    # The legend of the shown kinds' colours.
    shown = [(label, kind) for key, label, kind in LEGEND if getattr(scene, f"mge_show_{key}", False)]
    lx, ly = x, _bottom_inset(area) + 14 * scale
    if shown:  # a backdrop, so the outlines behind do not run through the words
        blf.size(0, 11 * scale)
        span = sum(26 * scale + blf.dimensions(0, label)[0] for label, _ in shown)
        _rect(lx - 8 * scale, ly - 5 * scale, span + 6 * scale, 24 * scale, PANEL)
    for label, kind in shown:
        colour = scene_io.COLORS.get(kind, (1.0, 0.95, 0.3, 1)) if kind else (1.0, 0.95, 0.3, 1)
        _rect(lx, ly + 2 * scale, 10 * scale, 10 * scale, colour)
        lx += 16 * scale + _text(lx + 15 * scale, ly + 2 * scale, label, 11, DIM, scale) + 10 * scale
    gpu.state.blend_set("NONE")


def _point_marker(context, path, scale):
    """A ring and the number at the path point the Punkte panel edits (scene.mge_point)."""
    import math

    from bpy_extras.view3d_utils import location_3d_to_region_2d
    spline = path.data.splines[0] if path.data.splines else None
    points = (spline.bezier_points if spline.type == "BEZIER" else spline.points) if spline else []
    if not points:
        return
    index = min(max(context.scene.mge_point, 1), len(points)) - 1
    co = points[index].co if spline.type == "BEZIER" else points[index].co.xyz
    spot = location_3d_to_region_2d(context.region, context.region_data, path.matrix_world @ co)
    if spot is None:
        return
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    radius = 11 * scale
    ring = [(spot.x + radius * math.cos(a / 16 * math.tau), spot.y + radius * math.sin(a / 16 * math.tau), 0.0)
            for a in range(17)]
    batch = batch_for_shader(shader, "LINE_STRIP", {"pos": ring})
    shader.uniform_float("viewportSize", (context.region.width, context.region.height))
    shader.uniform_float("lineWidth", 2.5 * scale)
    shader.uniform_float("color", HAZEL)
    batch.draw(shader)
    _text(spot.x + 14 * scale, spot.y + 8 * scale, f"Punkt {index + 1}", 12, TEXT, scale)


def _start_marker(context, scale):
    """The Teststart: a ring and "Mario-Start (Test)" at the 3D cursor, where Testspielen puts Mario."""
    import math

    from bpy_extras.view3d_utils import location_3d_to_region_2d
    spot = location_3d_to_region_2d(context.region, context.region_data, context.scene.cursor.location)
    if spot is None:
        return
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    shader.uniform_float("viewportSize", (context.region.width, context.region.height))
    shader.uniform_float("lineWidth", 3.0 * scale)
    shader.uniform_float("color", HAZEL)
    for radius in (14 * scale, 5 * scale):
        ring = [(spot.x + radius * math.cos(a / 20 * math.tau), spot.y + radius * math.sin(a / 20 * math.tau), 0.0)
                for a in range(21)]
        batch_for_shader(shader, "LINE_STRIP", {"pos": ring}).draw(shader)
    _text(spot.x + 18 * scale, spot.y + 6 * scale, "Mario-Start (Test)", 12, HAZEL, scale)


class MGE_MT_pie(bpy.types.Menu):
    bl_label = "Galaxie"
    bl_idname = "MGE_MT_pie"

    def draw(self, context):
        pie = self.layout.menu_pie()
        pie.operator("wm.tool_set_by_id", text="Setzen", icon="ADD").name = "mge.tool_place"
        pie.operator("wm.tool_set_by_id", text="Auswählen", icon="RESTRICT_SELECT_OFF").name = "builtin.select_box"
        pie.operator("wm.tool_set_by_id", text="Pfad zeichnen", icon="CURVE_BEZCURVE").name = "mge.tool_path"
        pie.operator("wm.tool_set_by_id", text="Schwerkraft", icon="FORCE_FORCE").name = "mge.tool_gravity"
        status = editor().game_io.testbed_status_known()
        here = bool(status) and (status.get("stage"), status.get("scenario")) == (context.scene.get("smg_galaxy"),
                                                                                   context.scene.mge_scenario)
        pie.operator("mge.testplay", text="Änderungen ins Testspiel (F5)" if here else "Testspielen (F5)", icon="PLAY")
        pie.operator("mge.save_mod", text="Speichern (⌘S)", icon="FILE_TICK")
        pie.operator("mge.preview", text="Automatisch testen", icon="RENDER_STILL")
        pie.operator("mge.view_start", text="Zum Start", icon="HOME")


class MGE_OT_pie(bpy.types.Operator):
    bl_idname = "mge.pie"
    bl_label = "Galaxie-Kreismenü"

    @classmethod
    def poll(cls, context):
        return context.workspace is not None and context.workspace.name == "Galaxie" and context.mode == "OBJECT"

    def execute(self, context):
        bpy.ops.wm.call_menu_pie(name=MGE_MT_pie.bl_idname)
        return {"FINISHED"}


_keymaps = []


def register():
    global _handle
    bpy.utils.register_class(MGE_MT_pie)
    bpy.utils.register_class(MGE_OT_pie)
    _handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), "WINDOW", "POST_PIXEL")
    keyconfig = bpy.context.window_manager.keyconfigs.addon
    if keyconfig is not None:
        keymap = keyconfig.keymaps.new(name="3D View", space_type="VIEW_3D")
        _keymaps.append((keymap, keymap.keymap_items.new(MGE_OT_pie.bl_idname, "Q", "PRESS")))


def unregister():
    global _handle
    for keymap, item in _keymaps:
        keymap.keymap_items.remove(item)
    _keymaps.clear()
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    bpy.utils.unregister_class(MGE_OT_pie)
    bpy.utils.unregister_class(MGE_MT_pie)

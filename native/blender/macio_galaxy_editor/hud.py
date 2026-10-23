"""Markers in the Galaxie workspace's viewport (gpu and blf in a POST_PIXEL draw handler), and the Q pie.

- The path point the Punkte panel edits, and the Teststart ring where Mario begins a test.
- Q (in this workspace only; elsewhere Blender's Quick Favorites): a pie with the editor's tools, the
  automatic test, saving, test play (the testbed) and playing in the whole game.
"""
import sys

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

HAZEL = (0.541, 0.353, 0.196, 1.0)
TEXT = (0.92, 0.93, 0.96, 1.0)
_handle = None


def editor():
    return sys.modules[__package__]




def _text(x, y, text, size, colour, scale):
    blf.size(0, size * scale)
    blf.color(0, *colour)
    blf.position(0, x, y, 0)
    blf.draw(0, text)
    return blf.dimensions(0, text)[0]








def draw():
    """Only markers in the view: the path point the Punkte panel edits and the Teststart; what is open
    and what is unsaved are the header's (workspace.py)."""
    context = bpy.context
    if context.workspace is None or context.workspace.name != "Galaxie" or context.region is None:
        return
    scene = context.scene
    if not scene.get("smg_galaxy"):
        return
    scale = context.preferences.system.ui_scale
    gpu.state.blend_set("ALPHA")
    active = context.active_object
    if active is not None and active.get("smg_kind") == "path" and active.mode == "OBJECT":
        _point_marker(context, active, scale)
    if scene.mge_warp:
        _start_marker(context, scale)
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

"""Thick outlines for the galaxy's wire shapes (areas, cameras, gravity) and its paths, in their kinds' colours.

Blender draws wires one pixel wide, too thin to tell the legend's colours apart, and has no width per
object. This draws them again over its own (a POST_VIEW handler, depth-tested, so planets still hide
what is behind them) with the width the Anzeigen panel sets (scene.mge_line_width; 0 = Blender's own
lines only). Selected ones are lighter and wider. Each object's lines are a batch in its own space,
kept until its mesh or curve changes.
"""
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils.geometry import interpolate_bezier

from . import scene_io

PATH_COLOUR = (1.0, 0.95, 0.3, 1.0)
CURVE_STEPS = 12  # segments per path section
_cache = {}  # object name -> (key, batch)
_handle = None


def _mesh_lines(mesh):
    co = np.empty(len(mesh.vertices) * 3, np.float32)
    mesh.vertices.foreach_get("co", co)
    edges = np.empty(len(mesh.edges) * 2, np.int32)
    mesh.edges.foreach_get("vertices", edges)
    return co.reshape(-1, 3)[edges]


def _curve_lines(curve):
    lines = []
    for spline in curve.splines:
        points = list(spline.bezier_points)
        pairs = list(zip(points, points[1:])) + ([(points[-1], points[0])] if spline.use_cyclic_u and points else [])
        for a, b in pairs:
            samples = interpolate_bezier(a.co, a.handle_right, b.handle_left, b.co, CURVE_STEPS + 1)
            for p, q in zip(samples, samples[1:]):
                lines += [p[:], q[:]]
    return lines


def _key(obj):
    data = obj.data
    if obj.type == "MESH":
        return data.as_pointer(), len(data.vertices), len(data.edges)
    return data.as_pointer(), tuple(c for s in data.splines for p in s.bezier_points
                                    for v in (p.co, p.handle_left, p.handle_right) for c in v)


def _batch(obj, shader):
    key = _key(obj)
    cached = _cache.get(obj.name)
    if cached is not None and cached[0] == key:
        return cached[1]
    lines = _mesh_lines(obj.data) if obj.type == "MESH" else _curve_lines(obj.data)
    batch = batch_for_shader(shader, "LINES", {"pos": lines}) if len(lines) else None
    _cache[obj.name] = (key, batch)
    return batch


def draw():
    context = bpy.context
    scene = context.scene
    if not scene.get("smg_galaxy") or context.workspace is None or context.workspace.name != "Galaxie":
        return
    width = scene.mge_line_width
    root = bpy.data.collections.get(f"SMG {scene['smg_galaxy']}")
    if width <= 0 or root is None:
        return
    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    shader.uniform_float("viewportSize", (context.region.width, context.region.height))
    scale = context.preferences.system.ui_scale
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("LESS_EQUAL")
    gpu.state.depth_mask_set(False)
    for obj in root.all_objects:
        kind = obj.get("smg_kind")
        if not (kind in scene_io.WIRE and obj.type == "MESH" or kind == "path" and obj.type == "CURVE"):
            continue
        if not obj.visible_get() or obj.mode != "OBJECT":
            continue
        batch = _batch(obj, shader)
        if batch is None:
            continue
        colour = PATH_COLOUR if kind == "path" else scene_io.COLORS.get(kind, (1, 1, 1, 1))
        selected = obj.select_get()
        if selected:
            colour = tuple(c + (1 - c) * 0.55 for c in colour[:3]) + (1.0,)
        else:
            colour = colour[:3] + (0.85,)  # a little of what is behind shows through where lines crowd
        shader.uniform_float("lineWidth", width * scale * (1.6 if selected else 1.0))
        shader.uniform_float("color", colour)
        with gpu.matrix.push_pop():
            gpu.matrix.multiply_matrix(obj.matrix_world)
            batch.draw(shader)
    gpu.state.depth_mask_set(True)
    gpu.state.depth_test_set("NONE")
    gpu.state.blend_set("NONE")


def _redraw(self, context):
    for window in context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.tag_redraw()


def register():
    global _handle
    bpy.types.Scene.mge_line_width = bpy.props.FloatProperty(
        name="Linienstärke", default=2.5, min=0.0, max=8.0, step=50, precision=1, update=_redraw,
        description="Wie dick Bereiche, Kamerabereiche, Schwerkraft und Pfade gezeichnet werden (Pixel; 0 = Blenders dünne Linien)")
    _handle = bpy.types.SpaceView3D.draw_handler_add(draw, (), "WINDOW", "POST_VIEW")


def unregister():
    global _handle
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
        _handle = None
    _cache.clear()
    del bpy.types.Scene.mge_line_width

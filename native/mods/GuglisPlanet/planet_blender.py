"""Guglis Testplanet in Blender (native/CUSTOM_GALAXY.md, "Your own planet").

Run with Blender (headless is fine):

    /Applications/Blender.app/Contents/MacOS/Blender --background --python planet_blender.py -- OUT_DIR

It builds the planet as editable Blender objects, saves OUT_DIR/GuglisTestPlanet.blend, and exports
OUT_DIR/GuglisTestPlanet.npz for native/mods/GuglisPlanet/build.py (game model and collision).

Modelling conventions, so that the export works for your own edits too:
- Units: 1 Blender metre = 100 game units (Mario is about 1.6 m). Blender's Z is the game's up (Y).
- Every mesh object of the collection "Planet" is exported. Its material slots must be named after
  the game materials of the template planet (StardustHillPlanet): "Green_v" (grass), "Ground_v"
  (soil), "CutStone_v" (cut stone).
- The colour attribute "Col" is the baked shading the game shows, as Blender shows it (sRGB; grey
  40..230: darker in hollows);
  UVs come from the export (box mapping at the texture's own density), so you need none.
- Objects in the collection "Markers" are not drawn: their names and positions go to the galaxy
  (Mario's start, the spin boxes, the star).
"""
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector, noise

RADIUS = 12.0  # metres: 1200 game units
SEED = 7


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def collection(name):
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    return col


def material(name, rgb):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1.0)
    return mat


def path_weight(direction):
    """How much of the soil path lies here: a winding band around the planet."""
    lon = math.atan2(direction.y, direction.x)
    lat = math.asin(max(-1.0, min(1.0, direction.z)))
    centre = 0.35 * math.sin(2.0 * lon) + 0.15 * math.sin(5.0 * lon + 1.0)
    distance = abs(lat - centre)
    return max(0.0, 1.0 - distance / 0.13)


def build_planet(col, mats):
    mesh = bpy.data.meshes.new("GuglisTestPlanet")
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=5, radius=RADIUS)
    for vert in bm.verts:
        direction = vert.co.normalized()
        hills = 0.45 * noise.noise(direction * 2.2 + Vector((SEED, 0, 0))) + 0.18 * noise.noise(direction * 6.0)
        flatten = path_weight(direction)  # the path is a little lower and smoother
        vert.co = direction * (RADIUS + hills * (1.0 - 0.7 * flatten) - 0.12 * flatten)
    bm.normal_update()
    color_layer = bm.loops.layers.color.new("Col")
    for face in bm.faces:
        centre = face.calc_center_median().normalized()
        face.material_index = 1 if path_weight(centre) > 0.35 else 0  # 0 grass, 1 soil
        for loop in face.loops:
            direction = loop.vert.co.normalized()
            height = loop.vert.co.length - RADIUS  # -0.6 .. +0.6
            speckle = 0.06 * noise.noise(direction * 40.0)
            if face.material_index == 0:
                shade = 0.72 + 0.32 * height + speckle
            else:
                shade = 0.48 + 0.2 * height + speckle
            shade = max(0.2, min(0.92, shade))
            loop[color_layer] = (shade, shade, shade, 1.0)
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True
    obj = bpy.data.objects.new("GuglisTestPlanet", mesh)
    obj.data.materials.append(mats["Green_v"])
    obj.data.materials.append(mats["Ground_v"])
    col.objects.link(obj)
    return obj


def surface_point(direction):
    """A point on the planet's ground along a direction (the hills' formula, without the path)."""
    direction = direction.normalized()
    hills = 0.45 * noise.noise(direction * 2.2 + Vector((SEED, 0, 0))) + 0.18 * noise.noise(direction * 6.0)
    flatten = path_weight(direction)
    return direction * (RADIUS + hills * (1.0 - 0.7 * flatten) - 0.12 * flatten)


def build_pillar(col, mats, name, direction, height, radius):
    """A six-sided cut-stone pillar standing on the ground, sunk 0.6 m into it."""
    direction = direction.normalized()
    base = surface_point(direction) - direction * 0.6
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=radius, radius2=radius * 0.85, depth=height + 0.6)
    color_layer = bm.loops.layers.color.new("Col")
    for face in bm.faces:
        top = face.normal.z > 0.9
        for loop in face.loops:
            z = (loop.vert.co.z + (height + 0.6) / 2) / (height + 0.6)  # 0 bottom .. 1 top
            shade = 0.85 if top else 0.55 + 0.3 * z
            loop[color_layer] = (shade, shade, shade, 1.0)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mats["CutStone_v"])
    up = Vector((0, 0, 1))
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = up.rotation_difference(direction)
    obj.location = base + direction * ((height + 0.6) / 2)
    col.objects.link(obj)
    return obj


def marker(col, name, location):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "SPHERE"
    obj.empty_display_size = 0.5
    obj.location = location
    col.objects.link(obj)
    return obj


def build_scene():
    clear_scene()
    planet_col = collection("Planet")
    marker_col = collection("Markers")
    mats = {
        "Green_v": material("Green_v", (0.35, 0.7, 0.25)),
        "Ground_v": material("Ground_v", (0.45, 0.3, 0.18)),
        "CutStone_v": material("CutStone_v", (0.55, 0.55, 0.55)),
    }
    build_planet(planet_col, mats)
    # Four pillars around the path; the tallest at the far side holds the star's place.
    pillars = [
        ("PillarA", Vector((0.9, 0.35, 0.25)), 2.2, 0.9),
        ("PillarB", Vector((-0.6, 0.8, -0.1)), 3.0, 1.0),
        ("PillarC", Vector((-0.5, -0.75, 0.4)), 1.6, 0.8),
        ("PillarD", Vector((0.2, -0.6, -0.8)), 4.0, 1.2),
    ]
    for name, direction, height, radius in pillars:
        build_pillar(planet_col, mats, name, direction, height, radius)
    # Markers: Mario lands on the north pole; three spin boxes float just above the ground (in spin
    # reach); the star comes out above the tallest pillar and flies down beside it, where Mario can
    # reach it.
    north = Vector((0, 0, 1))
    marker(marker_col, "MarioStart", surface_point(north) + north * 0.1)
    for index, direction in enumerate([Vector((0.5, 0.3, 0.8)), Vector((-0.45, 0.55, 0.7)), Vector((0.05, -0.65, 0.75))]):
        d = direction.normalized()
        marker(marker_col, f"SpinBox{index + 1}", surface_point(d) + d * 0.5)
    d = pillars[3][1].normalized()
    marker(marker_col, "StarAppear", surface_point(d) + d * (pillars[3][2] + 1.5))
    beside = (d + Vector((0.25, 0.0, 0.0)).cross(d)).normalized()  # about 3 m from the pillar
    marker(marker_col, "Star", surface_point(beside) + beside * 1.3)


def triangulated_arrays(obj):
    """World-space triangles of an object: positions, normals, colours, material slot per triangle."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    matrix = obj.matrix_world
    rotation = matrix.to_3x3().normalized()
    colors = mesh.color_attributes.get("Col")
    positions, normals, shades, materials = [], [], [], []
    for tri in mesh.loop_triangles:
        for loop_index in tri.loops:
            loop = mesh.loops[loop_index]
            positions.append(tuple(matrix @ mesh.vertices[loop.vertex_index].co))
            normal = tri.normal if not tri.use_smooth else loop.normal
            normals.append(tuple((rotation @ normal).normalized()))
            shades.append(tuple(colors.data[loop_index].color_srgb[:3]) if colors is not None and colors.domain == "CORNER" else (0.7, 0.7, 0.7))
        materials.append(obj.material_slots[tri.material_index].material.name)
    evaluated.to_mesh_clear()
    return positions, normals, shades, materials


def export(out_dir: Path):
    positions, normals, shades, materials = [], [], [], []
    for obj in bpy.data.collections["Planet"].objects:
        if obj.type != "MESH":
            continue
        p, n, s, m = triangulated_arrays(obj)
        positions += p
        normals += n
        shades += s
        materials += m
    markers = {obj.name: tuple(obj.location) for obj in bpy.data.collections["Markers"].objects}
    names = sorted(set(materials))
    np.savez(
        out_dir / "GuglisTestPlanet.npz",
        positions=np.array(positions, dtype=np.float32),  # metres, Blender axes, 3 per triangle
        normals=np.array(normals, dtype=np.float32),
        shades=np.array(shades, dtype=np.float32),
        material=np.array([names.index(m) for m in materials], dtype=np.int32),
        material_names=np.array(names),
        marker_names=np.array(list(markers)),
        marker_positions=np.array(list(markers.values()), dtype=np.float32),
    )


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_dir = Path(args[0] if args else ".").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    blend = out_dir / "GuglisTestPlanet.blend"
    if "--from-blend" in args and blend.exists():
        bpy.ops.wm.open_mainfile(filepath=str(blend))  # export your own edits
    else:
        build_scene()
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    export(out_dir)
    print(f"GUGLIS PLANET: wrote {blend} and {out_dir / 'GuglisTestPlanet.npz'}")


main()

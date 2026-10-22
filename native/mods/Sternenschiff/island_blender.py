"""Guglis' sky island for the Comet Observatory, in Blender (native/mods/Sternenschiff/build.py).

Run with Blender (headless is fine):

    /Applications/Blender.app/Contents/MacOS/Blender --background --python island_blender.py -- OUT_DIR [--from-blend]

It builds the island as an editable Blender object (a grassy top on a rock that tapers to a point
below, like the observatory's own floating islands), saves OUT_DIR/GuglisSkyIsland.blend and
exports OUT_DIR/GuglisSkyIsland.npz for build.py. --from-blend exports your edited .blend instead.

The conventions are the test planet's (native/mods/GuglisPlanet/planet_blender.py): 1 m = 100 game
units, Z up; meshes in the collection "Planet" with material slots named after the template's
materials ("Green_v" grass, "Ground_v" soil, "CutStone_v" stone); shading in the colour attribute
"Col". The island's top is at height 0, its centre at the origin.
"""
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector, noise

SEGMENTS = 48
# The lathe profile, top centre to bottom tip: (radius, height) in metres.
PROFILE = [(0.0, 0.18), (1.0, 0.17), (2.0, 0.15), (3.0, 0.12), (4.0, 0.09), (5.0, 0.06), (6.0, 0.03), (6.8, 0.0),
           (7.2, -0.25), (7.1, -0.8), (6.6, -1.6), (5.6, -2.6), (4.4, -3.6), (3.1, -4.6), (1.8, -5.6), (0.8, -6.4),
           (0.0, -7.0)]
GRASS_RINGS = 8  # the first profile points are the grassy top


def material(name, rgb):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = (*rgb, 1.0)
    return mat


def build_island(col, mats):
    bm = bmesh.new()
    rings = []
    for index, (radius, height) in enumerate(PROFILE):
        ring = []
        count = 1 if radius == 0.0 else SEGMENTS
        for step in range(count):
            angle = 2.0 * math.pi * step / SEGMENTS
            wobble = 1.0 + (0.04 * noise.noise(Vector((math.cos(angle) * 2.0, math.sin(angle) * 2.0, index * 0.7))) if index > GRASS_RINGS - 2 else 0.0)
            bump = 0.08 * noise.noise(Vector((math.cos(angle) * radius * 0.6, math.sin(angle) * radius * 0.6, 3.0))) if index < GRASS_RINGS - 1 else 0.0
            ring.append(bm.verts.new((radius * wobble * math.cos(angle), radius * wobble * math.sin(angle), height + bump)))
        rings.append(ring)
    faces = []
    for index in range(len(rings) - 1):
        upper, lower = rings[index], rings[index + 1]
        kind = 0 if index < GRASS_RINGS - 1 else 1  # 0 grass, 1 soil
        for step in range(SEGMENTS):
            nxt = (step + 1) % SEGMENTS
            if len(upper) == 1:
                faces.append((bm.faces.new((upper[0], lower[step], lower[nxt])), kind))
            elif len(lower) == 1:
                faces.append((bm.faces.new((upper[step], lower[0], upper[nxt])), kind))
            else:
                faces.append((bm.faces.new((upper[step], lower[step], lower[nxt], upper[nxt])), kind))
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    color_layer = bm.loops.layers.color.new("Col")
    for face in bm.faces:
        centre = face.calc_center_median()
        face.material_index = 0 if face.normal.z > 0.6 and centre.z > -0.1 else 1
        for loop in face.loops:
            p = loop.vert.co
            speckle = 0.05 * noise.noise(p * 3.0)
            if face.material_index == 0:
                edge = max(0.0, (Vector((p.x, p.y, 0)).length - 5.5) / 1.5)  # darker towards the rim
                shade = 0.8 + speckle - 0.12 * edge
            else:
                shade = 0.7 + 0.08 * p.z + speckle  # darker towards the tip
            shade = max(0.25, min(0.92, shade))
            loop[color_layer] = (shade, shade, shade, 1.0)
    mesh = bpy.data.meshes.new("GuglisSkyIsland")
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True
    obj = bpy.data.objects.new("GuglisSkyIsland", mesh)
    obj.data.materials.append(mats["Green_v"])
    obj.data.materials.append(mats["Ground_v"])
    col.objects.link(obj)


def build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    col = bpy.data.collections.new("Planet")
    bpy.context.scene.collection.children.link(col)
    bpy.context.scene.collection.children.link(bpy.data.collections.new("Markers"))
    mats = {"Green_v": material("Green_v", (0.35, 0.7, 0.25)), "Ground_v": material("Ground_v", (0.45, 0.3, 0.18))}
    build_island(col, mats)


def export(out_dir: Path):
    # The test planet's exporter: world-space triangles, normals, sRGB shading, material per triangle.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "GuglisPlanet"))
    positions, normals, shades, materials = [], [], [], []
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.data.collections["Planet"].objects:
        if obj.type != "MESH":
            continue
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        matrix = obj.matrix_world
        rotation = matrix.to_3x3().normalized()
        colors = mesh.color_attributes.get("Col")
        for tri in mesh.loop_triangles:
            for loop_index in tri.loops:
                loop = mesh.loops[loop_index]
                positions.append(tuple(matrix @ mesh.vertices[loop.vertex_index].co))
                normal = loop.normal if tri.use_smooth else tri.normal
                normals.append(tuple((rotation @ normal).normalized()))
                shades.append(tuple(colors.data[loop_index].color_srgb[:3]) if colors is not None and colors.domain == "CORNER" else (0.7, 0.7, 0.7))
            materials.append(obj.material_slots[tri.material_index].material.name)
        evaluated.to_mesh_clear()
    names = sorted(set(materials))
    np.savez(out_dir / "GuglisSkyIsland.npz", positions=np.array(positions, dtype=np.float32),
             normals=np.array(normals, dtype=np.float32), shades=np.array(shades, dtype=np.float32),
             material=np.array([names.index(m) for m in materials], dtype=np.int32), material_names=np.array(names),
             marker_names=np.array([], dtype=str), marker_positions=np.zeros((0, 3), dtype=np.float32))


def main():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out_dir = Path(args[0] if args else ".").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    blend = out_dir / "GuglisSkyIsland.blend"
    if "--from-blend" in args and blend.exists():
        bpy.ops.wm.open_mainfile(filepath=str(blend))
    else:
        build_scene()
        bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    export(out_dir)
    print(f"GUGLIS ISLAND: wrote {blend} and {out_dir / 'GuglisSkyIsland.npz'}")


main()

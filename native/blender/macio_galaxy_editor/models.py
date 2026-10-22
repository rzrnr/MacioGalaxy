"""The game's models in Blender: an object's archive, its J3D model as a mesh with textured materials.

- Which model: ObjectData/<Name>.arc (the disc, or the winning enabled mod), or the archive Whitehole's
  modelsubstitutions.json names for objects whose model is called otherwise (BenefitItemOneUp ->
  KinokoOneUp, ...). Inside, <name>.bdl/.bmd. Objects without one keep their stand-in.
- The model is posed at rest (native/tools/j3d_scene.py) and converted once: its geometry to
  ~/Library/Caches/MacioGalaxyEditor/models/<hash>.npz, its textures to .../textures/<hash>.png. In a
  Blender session each model is one mesh ("SMG Model <Name>") that every object of that name shares.
- Materials approximate the game's: the texture TEV stage 0 samples (its wrap modes, its UV set)
  times the vertex colours or the material colour, alpha clip or blend, backface culling.
  Environment-mapped textures (no UV set) are left out; the colours remain.
"""
import hashlib
import json
from pathlib import Path

import bpy
import numpy as np

from .convert import C, UNIT
from .galaxy import GameData, REPO

import sys  # noqa: E402

sys.path.insert(0, str(REPO / "native/tools"))
from gx_texture import decode_tex1, write_png  # noqa: E402
from j3d_scene import MeshPart, ModelMesh, posed_model  # noqa: E402
from rarc_tree import read_tree  # noqa: E402

CACHE = Path.home() / "Library/Caches/MacioGalaxyEditor"
VERSION = "2"  # bump when the conversion changes: old cache entries are then ignored
WRAP = {0: "EXTEND", 1: "REPEAT", 2: "MIRROR"}
# Observatory pieces add their dome to the name, by Obj_arg0 1..6 (AstroMapObjFunction::getModelName).
DOMES = ("Observatory", "Well", "Kitchen", "BedRoom", "Machine", "Tower")
DOME_MODELS = {"AstroDome": [f"AstroDome{d}" for d in DOMES], "AstroDomeEntrance": [f"AstroDomeEntrance{d}" for d in DOMES],
               "AstroStarPlate": [f"AstroStarPlate{d}" for d in DOMES], "AstroDomeSky": ["AstroDomeSkyA", "AstroDomeSkyB", "AstroDomeSkyC"] * 2}
EXTRA_SUBSTITUTIONS = {"kinopioastro": "Kinopio", "superspindriverhazel": "SuperSpinDriver"}  # not in Whitehole's list
_substitutions = None


def substitutions():
    global _substitutions
    if _substitutions is None:
        path = REPO.parent / "Whitehole/src/data/modelsubstitutions.json"
        _substitutions = {k.lower(): v for k, v in json.loads(path.read_text()).items()} if path.exists() else {}
        _substitutions.update(EXTRA_SUBSTITUTIONS)
    return _substitutions


def archive_name(name: str, values: dict | None = None) -> str:
    """The archive an object's model comes from."""
    table = DOME_MODELS.get(name)
    if table is not None:
        dome = (values or {}).get("Obj_arg0", -1)
        return table[dome - 1] if isinstance(dome, int) and 1 <= dome <= len(table) else name
    return substitutions().get(name.lower(), name)


def model_bytes(game: GameData, name: str, values: dict | None = None):
    """(model file bytes, archive name) for an object (name and fields), or (None, None)."""
    for archive in dict.fromkeys([archive_name(name, values), name]):
        path, _ = game.locate(f"ObjectData/{archive}.arc")
        if path is None:
            continue
        files = read_tree(path.read_bytes()).files
        models = [p for p in files if p.lower().endswith((".bdl", ".bmd"))]
        if not models:
            continue
        models.sort(key=lambda p: (Path(p).stem.lower() != archive.lower(), p))
        return files[models[0]], archive
    return None, None


# --- the disk cache --------------------------------------------------------------------------


def _converted(data: bytes):
    """(ModelMesh with parts and materials, [texture png path or None]) for model bytes, cached."""
    key = hashlib.sha1(VERSION.encode() + data).hexdigest()[:20]
    folder = CACHE / "models"
    npz, meta = folder / f"{key}.npz", folder / f"{key}.json"
    if npz.exists() and meta.exists():
        info = json.loads(meta.read_text())
        arrays = np.load(npz)
        parts = []
        for i, part in enumerate(info["parts"]):
            get = (lambda k: arrays[f"{i}_{k}"] if f"{i}_{k}" in arrays else None)
            parts.append(MeshPart(part["material"], get("pos"), get("nrm"), get("uv"), get("col"), get("tri")))
        return ModelMesh(parts, info["materials"]), info["textures"]
    mesh = posed_model(data)
    textures = []
    (CACHE / "textures").mkdir(parents=True, exist_ok=True)
    for name, header, image, palette in mesh.textures:
        tkey = hashlib.sha1(VERSION.encode() + header + image + (palette or b"")).hexdigest()[:20]
        png = CACHE / "textures" / f"{tkey}.png"
        try:
            rgba = decode_tex1(header, image, palette)
            if not png.exists():
                write_png(png, rgba)
            weight = rgba[..., 3:4].astype(np.float64) + 1.0
            mean = ((rgba[..., :3] * weight).sum((0, 1)) / weight.sum()).tolist()
            textures.append(dict(path=str(png), name=name, wrap=[header[6], header[7]], mean=mean))
        except (ValueError, KeyError):
            textures.append(None)
    arrays = {}
    for i, part in enumerate(mesh.parts):
        for k, v in (("pos", part.positions), ("nrm", part.normals), ("uv", part.uvs), ("col", part.colors), ("tri", part.triangles)):
            if v is not None:
                arrays[f"{i}_{k}"] = v
    folder.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(npz, **arrays)
    meta.write_text(json.dumps(dict(parts=[dict(material=p.material) for p in mesh.parts], materials=mesh.materials,
                                    textures=textures)))
    return ModelMesh(mesh.parts, mesh.materials), textures


# --- Blender ---------------------------------------------------------------------------------


def _image(path: str):
    image = bpy.data.images.load(path, check_existing=True)
    image.alpha_mode = "STRAIGHT"
    return image


def _material(model: str, index: int, info: dict, textures: list):
    name = f"SMG {model} {info['name']}"
    material = bpy.data.materials.get(name)
    if material is not None:
        return material
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    shader = nodes.get("Principled BSDF")
    shader.inputs["Roughness"].default_value = 0.8
    color = [c / 255 for c in info["color"]]
    material.diffuse_color = color
    out_color, out_alpha = None, None
    texture = textures[info["texture"]] if info.get("texture") is not None and info["texture"] < len(textures) else None
    if texture and info.get("uv_set") is None:
        # An environment map (the coin's gold, the stars' shine): its mean colour stands in for it.
        color = [c / 255 for c in texture.get("mean", info["color"][:3])] + [1.0]
        material.diffuse_color = color
    if texture and info.get("uv_set") is not None:
        node = nodes.new("ShaderNodeTexImage")
        node.image = _image(texture["path"])
        node.extension = WRAP.get(texture["wrap"][0], "REPEAT")
        node.interpolation = "Linear"
        uv = nodes.new("ShaderNodeUVMap")
        uv.uv_map = f"UV{info['uv_set']}"
        links.new(uv.outputs["UV"], node.inputs["Vector"])
        out_color, out_alpha = node.outputs["Color"], node.outputs["Alpha"]
    if info.get("vertex_color"):
        attr = nodes.new("ShaderNodeVertexColor")
        attr.layer_name = "Col"
        if out_color is not None:
            mix = nodes.new("ShaderNodeMix")
            mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            links.new(out_color, mix.inputs["A"])
            links.new(attr.outputs["Color"], mix.inputs["B"])
            out_color = mix.outputs["Result"]
        elif texture:
            mix = nodes.new("ShaderNodeMix")
            mix.data_type, mix.blend_type = "RGBA", "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            mix.inputs["A"].default_value = color
            links.new(attr.outputs["Color"], mix.inputs["B"])
            out_color = mix.outputs["Result"]
        else:
            out_color = attr.outputs["Color"]
    if out_color is not None:
        links.new(out_color, shader.inputs["Base Color"])
    else:
        shader.inputs["Base Color"].default_value = color
    if out_alpha is not None and info.get("alpha") in ("clip", "blend"):
        links.new(out_alpha, shader.inputs["Alpha"])
        material.surface_render_method = "BLENDED" if info["alpha"] == "blend" else "DITHERED"
    material.use_backface_culling = info.get("cull") == "back"
    return material


def _mesh_from(model: str, mesh: ModelMesh, textures: list):
    parts = [p for p in mesh.parts if len(p.triangles)]
    blender = bpy.data.meshes.new(f"SMG Model {model}")
    if not parts:
        return blender
    offsets = np.cumsum([0] + [len(p.positions) for p in parts])
    positions = np.concatenate([p.positions for p in parts]) @ np.array(C).T * UNIT
    triangles = np.concatenate([p.triangles + offsets[i] for i, p in enumerate(parts)])
    blender.vertices.add(len(positions))
    blender.vertices.foreach_set("co", positions.astype(np.float32).ravel())
    blender.loops.add(len(triangles) * 3)
    blender.loops.foreach_set("vertex_index", triangles.astype(np.int32).ravel())
    blender.polygons.add(len(triangles))
    blender.polygons.foreach_set("loop_start", (np.arange(len(triangles)) * 3).astype(np.int32))
    slots = {}
    material_index = []
    for p in parts:
        if p.material not in slots:
            slots[p.material] = len(slots)
            blender.materials.append(_material(model, p.material, mesh.materials[p.material], textures))
        material_index.append(np.full(len(p.triangles), slots[p.material], np.int32))
    blender.polygons.foreach_set("material_index", np.concatenate(material_index))
    blender.update(calc_edges=True)
    corners = triangles.ravel()
    sets = sorted({m.get("uv_set") for m in mesh.materials if m.get("uv_set") is not None} | {0})
    for uv_set in sets:
        uv = np.zeros((len(positions), 2), np.float32)
        for i, p in enumerate(parts):
            if p.uvs is not None and uv_set == 0:
                uv[offsets[i]:offsets[i + 1]] = p.uvs
        uv[:, 1] = 1.0 - uv[:, 1]  # GX t grows downwards
        layer = blender.uv_layers.new(name=f"UV{uv_set}")
        layer.data.foreach_set("uv", uv[corners].ravel())
    if any(p.colors is not None for p in parts):
        colors = np.full((len(positions), 4), 255, np.uint8)
        for i, p in enumerate(parts):
            if p.colors is not None:
                colors[offsets[i]:offsets[i + 1]] = p.colors
        attr = blender.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
        attr.data.foreach_set("color_srgb", (colors[corners] / 255.0).astype(np.float32).ravel())
    if all(p.normals is not None for p in parts):
        normals = np.concatenate([p.normals for p in parts]) @ np.array(C).T
        lengths = np.linalg.norm(normals, axis=1, keepdims=True)
        normals = normals / np.where(lengths > 0, lengths, 1)
        blender.normals_split_custom_set_from_vertices(normals.astype(np.float32))
    blender["smg_model"] = model
    return blender


class ModelLibrary:
    """The models of one import (or session): name -> Blender mesh, or None when there is none."""

    def __init__(self, game: GameData):
        self.game = game
        self.meshes = {}
        self.failed = {}

    def mesh(self, name: str, values: dict | None = None):
        key = archive_name(name, values)
        if key in self.meshes:
            return self.meshes[key]
        result = None
        try:
            data, archive = model_bytes(self.game, name, values)
            if data is not None:
                existing = bpy.data.meshes.get(f"SMG Model {archive}")
                if existing is not None and existing.get("smg_model") == archive:
                    result = existing
                else:
                    mesh, textures = _converted(data)
                    result = _mesh_from(archive, mesh, textures)
        except Exception as error:  # a model this reader cannot read keeps its stand-in
            self.failed[key] = str(error)
        self.meshes[key] = result
        return result

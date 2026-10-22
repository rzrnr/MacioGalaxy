#!/usr/bin/env python3
"""A J3D model (.bdl/.bmd) as posed triangle meshes with simple materials, for viewing (the editor).

j3d_mesh.Model reads the blocks; this adds what drawing the model at rest needs:
- JNT1 joints (scale, rotation in 1/32768 of half a turn, translation) placed by the INF1 tree:
  world = parent . T . Rz . Ry . Rx . S;
- DRW1 draw matrices: a vertex's PNMTXIDX/3 picks an entry of its packet's matrix table (0xFFFF:
  the previous packet's), which names a joint (rigid: the vertex is in the joint's space) or an EVP1
  envelope (skinned: the vertex is already in model space at rest);
- display lists decoded with numpy (every draw is a run of fixed-size vertex records);
- per material a summary a viewer can use: the texture TEV stage 0 samples and its UV set, whether
  channel 0 takes vertex colours or the material colour, alpha test/blend, culling, wrap modes.

    posed_model(data: bytes) -> ModelMesh(parts, materials, textures)
    j3d_scene.py info MODEL_OR_ARC
"""
import math
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gx_texture import texture_entries  # noqa: E402
from j3d_mesh import (CLR0, COLOR_SIZE, COMP_SIZE, F32, INDEX8, INDEX16, NONE, NRM, POS, PRIMS, TEX0, Model,  # noqa: E402
                      load_model_bytes, s16, u16, u32)


@dataclass
class MeshPart:
    material: int
    positions: np.ndarray        # (n, 3) model space, game units
    normals: np.ndarray | None   # (n, 3)
    uvs: np.ndarray | None       # (n, 2) GX s, t (t grows downwards)
    colors: np.ndarray | None    # (n, 4) uint8
    triangles: np.ndarray        # (m, 3) counter-clockwise


@dataclass
class ModelMesh:
    parts: list = field(default_factory=list)
    materials: list = field(default_factory=list)   # dicts, see material_summary
    textures: list = field(default_factory=list)    # (name, header, image, palette)


def _matrix(scale, rot, trans):
    rx, ry, rz = (math.radians(a) for a in rot)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    rotx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    roty = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rotz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    m = np.eye(4)
    m[:3, :3] = rotz @ roty @ rotx @ np.diag(scale)
    m[:3, 3] = trans
    return m


def joint_matrices(model: Model):
    """Each joint's matrix in model space at rest."""
    b = model.blocks["JNT1"]
    count = u16(b, 8)
    init, index = u32(b, 0x0C), u32(b, 0x10)
    local = []
    for j in range(count):
        r = init + u16(b, index + 2 * j) * 0x40
        scale = struct.unpack_from(">3f", b, r + 4)
        rot = [s16(b, r + 0x10 + 2 * k) * 180.0 / 32768.0 for k in range(3)]
        trans = struct.unpack_from(">3f", b, r + 0x18)
        local.append(_matrix(scale, rot, trans))
    world = [np.eye(4)] * count
    stack, last = [], None
    for kind, value in model.hierarchy:
        if kind == 0x01:
            stack.append(last)
        elif kind == 0x02:
            stack.pop()
        elif kind == 0x10:
            parent = next((p for p in reversed(stack) if p is not None), None)
            world[value] = (world[parent] if parent is not None else np.eye(4)) @ local[value]
            last = value
        elif kind == 0x00:
            break
    return world


def draw_matrices(model: Model, joints):
    """Per DRW1 entry: the matrix to apply to its vertices (identity for envelopes)."""
    if "DRW1" not in model.blocks:
        return [joints[0] if joints else np.eye(4)]
    b = model.blocks["DRW1"]
    count = u16(b, 8)
    weighted, data = u32(b, 0x0C), u32(b, 0x10)
    out = []
    for i in range(count):
        if b[weighted + i]:
            out.append(None)  # an envelope: the vertex is in model space at rest
        else:
            out.append(joints[u16(b, data + 2 * i)])
    return out


def _record_dtype(model: Model, desc):
    fields = []
    for attr, typ in sorted(desc):
        if typ == NONE:
            continue
        if attr <= 8:
            fields.append((f"a{attr}", "u1"))
        elif typ == INDEX8:
            fields.append((f"a{attr}", "u1"))
        elif typ == INDEX16:
            fields.append((f"a{attr}", ">u2"))
        else:
            cnt, ctype, _ = model.vtx_fmt.get(attr, (1, F32, 0))
            if attr in (CLR0, CLR0 + 1):
                size = COLOR_SIZE[ctype]
            else:
                ncomp = {POS: 2 + cnt, NRM: 3 if cnt == 0 else 9}.get(attr, 1 + cnt)
                size = COMP_SIZE[ctype] * ncomp
            fields.append((f"d{attr}", f"V{size}"))  # direct data: not used for viewing
    return np.dtype(fields)


def _draws(dl: bytes, dtype):
    """(primitive, records) for each draw command of a display list."""
    p, out = 0, []
    while p < len(dl):
        op = dl[p]
        if op == 0x00:
            p += 1
        elif op & 0xF8 in PRIMS:
            count = u16(dl, p + 1)
            p += 3
            records = np.frombuffer(dl, dtype=dtype, count=count, offset=p)
            out.append((op & 0xF8, records))
            p += count * dtype.itemsize
        elif op == 0x08:
            p += 6
        elif op == 0x10:
            p += 5 + 4 * ((u32(dl, p + 1) >> 16) + 1)
        elif op in (0x20, 0x28, 0x30, 0x38, 0x61):
            p += 5
        elif op == 0x40:
            p += 9
        elif op == 0x48:
            p += 1
        else:
            break  # padding or an unknown command: the rest is not drawn
    return out


def _triangle_indices(prim, n):
    """Index triples (counter-clockwise) into a run of n vertices."""
    if prim == 0x90:
        t = np.arange(n - n % 3).reshape(-1, 3)
    elif prim == 0x98:
        i = np.arange(max(n - 2, 0))
        t = np.stack([i, i + 1, i + 2], 1)
        odd = i % 2 == 1
        t[odd] = t[odd][:, [1, 0, 2]]
    elif prim == 0xA0:
        i = np.arange(1, max(n - 1, 1))
        t = np.stack([np.zeros_like(i), i, i + 1], 1)
    elif prim == 0x80:
        q = np.arange(n - n % 4).reshape(-1, 4)
        t = np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
    else:
        return np.zeros((0, 3), np.int64)
    return t[:, [0, 2, 1]]  # GX clockwise -> counter-clockwise


def material_summary(model: Model, m: int) -> dict:
    info = model.material(m)
    orders = [o for o in info["tev_orders"] if o]
    texmap = orders[0][1] if orders and orders[0][1] != 0xFF else (info["textures"][0][0] if info["textures"] else None)
    texcoord = orders[0][0] if orders and orders[0][0] != 0xFF else 0
    texture = next((t for slot, t, _ in info["textures"] if slot == texmap), None) if texmap is not None else None
    uv_set = None
    if texture is not None and texcoord < len(info["texgens"]) and info["texgens"][texcoord]:
        src = info["texgens"][texcoord]["src"]
        uv_set = src - 4 if 4 <= src <= 11 else None  # None: generated (environment) coordinates
    chan = info["chans"][0]
    alpha_cmp = info["alpha_cmp"]
    blend = info["blend"]
    alpha = "opaque"
    if blend and blend[0] == 1:
        alpha = "blend"
    elif alpha_cmp and not (alpha_cmp[0] == 7 and alpha_cmp[3] == 7):
        alpha = "clip"
    return dict(name=info["name"], texture=texture, uv_set=uv_set, vertex_color=bool(chan and chan["mat_src"] == "vtx"),
                color=info["mat_color"][0] or (255, 255, 255, 255), alpha=alpha, cull=info["cull"])


def posed_model(data: bytes) -> ModelMesh:
    model = Model(data)
    joints = joint_matrices(model)
    draws = draw_matrices(model, joints)
    P, N = model.arrays.get(POS), model.arrays.get(NRM)
    C, T = model.arrays.get(CLR0), model.arrays.get(TEX0)
    mesh = ModelMesh(materials=[material_summary(model, m) for m in range(model.mat_num)],
                     textures=texture_entries(model.blocks["TEX1"]))
    for s, shape in enumerate(model.shapes):
        dtype = _record_dtype(model, shape["desc"])
        names = dtype.names
        pos, nrm, col, uv, tris = [], [], [], [], []
        table_prev = None
        base = 0
        for packet in shape["packets"]:
            table = [t if t != 0xFFFF else (table_prev[i] if table_prev and i < len(table_prev) else 0)
                     for i, t in enumerate(packet["table"])]
            table_prev = table
            for prim, rec in _draws(packet["dl"], dtype):
                n = len(rec)
                if n == 0 or "a9" not in names:
                    continue
                p = P[rec["a9"]][:, :3]
                q = N[rec["a10"]][:, :3] if N is not None and "a10" in names else None
                slot = (rec["a0"] // 3) if "a0" in names else np.zeros(n, np.int64)
                drw_index = np.array(table, np.int64)[np.minimum(slot, len(table) - 1)] if table else np.zeros(n, np.int64)
                p = p.copy()
                q = q.copy() if q is not None else None
                for d in np.unique(drw_index):
                    matrix = draws[d] if d < len(draws) else None
                    if matrix is None:
                        continue
                    sel = drw_index == d
                    p[sel] = p[sel] @ matrix[:3, :3].T + matrix[:3, 3]
                    if q is not None:
                        q[sel] = q[sel] @ matrix[:3, :3].T
                pos.append(p)
                nrm.append(q)
                col.append(C[rec["a11"]] if C is not None and "a11" in names else None)
                uv.append(T[rec["a13"]][:, :2] if T is not None and "a13" in names else None)
                tris.append(_triangle_indices(prim, n) + base)
                base += n
        if not pos:
            continue

        def joined(items):
            return np.concatenate(items) if items and all(i is not None for i in items) else None

        mesh.parts.append(MeshPart(model.shape_material.get(s, 0), np.concatenate(pos), joined(nrm), joined(uv), joined(col),
                                   np.concatenate(tris) if tris else np.zeros((0, 3), np.int64)))
    return mesh


def main(argv) -> int:
    if len(argv) != 2 or argv[0] != "info":
        print(__doc__)
        return 2
    mesh = posed_model(load_model_bytes(Path(argv[1]))[0])
    for part in mesh.parts:
        lo, hi = part.positions.min(0), part.positions.max(0)
        print(f"part material {part.material}: {len(part.positions)} vertices, {len(part.triangles)} triangles, "
              f"box {lo.round(1)}..{hi.round(1)}")
    for i, m in enumerate(mesh.materials):
        print(i, m)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

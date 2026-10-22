#!/usr/bin/env python3
"""Build a J3D model (.bdl/.bmd) from custom geometry, reusing a game model's materials.

The output keeps a template model's materials and textures byte for byte (MAT3, MDL3,
TEX1) and replaces its geometry: VTX1 (vertex arrays), SHP1 (shapes and display lists),
JNT1 (one static root joint), DRW1/EVP1 (one rigid draw matrix, no envelopes) and INF1
(hierarchy and counts). So a custom mesh is drawn with the template's TEV setup,
texture(s), lighting and blending, and looks like the planet it was taken from.

  j3d_mesh.py info MODEL                      materials, textures and what each material
                                              needs from the mesh (MODEL: .bdl/.bmd or an
                                              .arc containing one, Yaz0 or plain)
  j3d_mesh.py from-obj TEMPLATE OBJ OUT [--materials NAME=INDEX,...] [--scale S]
                                              write OUT (.bdl/.bmd, or .arc: the template's
                                              archive with its model replaced)
  j3d_mesh.py roundtrip MODEL                 rebuild MODEL from its own geometry and compare
  j3d_mesh.py check MODEL                     parse a model and validate every block/index
  j3d_mesh.py selftest [TEMPLATE]             build a cube with a template and re-parse it

Python API:
  build_model(template: bytes, parts: list[Part], name: str, fmt=None) -> bytes
  Part(material, positions (N,3), normals (N,3), uvs (N,2), triangles (M,3), colors (N,4) u8)
    material: index into the template's MAT3 (see `info`); triangles counter-clockwise when
    seen from outside (OBJ/Blender convention; the writer flips them to GX's clockwise);
    uvs as GX s,t (t grows downwards; from-obj uses t = 1 - v); normals None = smooth
    normals from the triangles; colors None = the template material's mean vertex color
    (planet "_v" materials take their baked shading from CLR0, so white looks flat).
  extract_parts(Model(data)) -> list[Part]   (a model's own geometry, same conventions)

Format notes (from src/JSystem/J3DGraphLoader and native/resource/j3d_model.cpp):
- ResourceHolder loads "<Name>.bdl" with loadBinaryDisplayList ('J3D2bdl4'; MAT3 + the
  optional MDL3 material display lists) and "<Name>.bmd" with load ('J3D2bmd3', MAT3 only).
  The output keeps the template's type unless fmt='bmd' (drops MDL3) is asked for.
- Every material gets exactly one shape (J3DMaterial holds one shape; MR::isEnvelope and
  other code dereference material->getShape(), so an unused material gets an empty shape).
- The native loader converts the big-endian file to host order block by block and rejects
  block types it does not know, so only INF1 VTX1 EVP1 DRW1 JNT1 SHP1 MAT3 MDL3 TEX1 are
  written. Display lists stay big-endian (GX byte streams).
- Vertex formats written: POS f32 xyz, NRM s16 frac 14, CLR rgba8, TEXn f32 st; every
  array attribute is GX_INDEX16 in the display lists (so at most 65535 entries per array,
  after de-duplication); primitives are GX_TRIANGLES (0x90) with GX_VTXFMT0.
"""
import argparse
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

# --- GX enums ---------------------------------------------------------------------------------

PNMTXIDX, TEX0MTXIDX = 0, 1  # TEX0MTXIDX..TEX7MTXIDX = 1..8
POS, NRM, CLR0, CLR1, TEX0 = 9, 10, 11, 12, 13  # TEX0..TEX7 = 13..20
NBT, NULL_ATTR = 25, 0xFF
NONE, DIRECT, INDEX8, INDEX16 = 0, 1, 2, 3
F32, S16, RGBA8 = 4, 3, 5
TRIANGLES = 0x90

ATTR_NAMES = {0: "PNMTXIDX", 9: "POS", 10: "NRM", 11: "CLR0", 12: "CLR1", 25: "NBT"}
ATTR_NAMES.update({1 + i: f"TEX{i}MTXIDX" for i in range(8)})
ATTR_NAMES.update({13 + i: f"TEX{i}" for i in range(8)})
COMP_SIZE = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4}
COMP_NAMES = {0: "u8", 1: "s8", 2: "u16", 3: "s16", 4: "f32"}
COLOR_SIZE = {0: 2, 1: 3, 2: 4, 3: 2, 4: 3, 5: 4}
PRIMS = {0x80: "quads", 0x90: "triangles", 0x98: "strip", 0xA0: "fan", 0xA8: "lines", 0xB0: "linestrip", 0xB8: "points"}
TEXGEN_SRC = {0: "POS", 1: "NRM", 2: "BINRM", 3: "TANGENT", 19: "COLOR0", 20: "COLOR1"}
TEXGEN_SRC.update({4 + i: f"TEX{i}" for i in range(8)})
TEXGEN_SRC.update({12 + i: f"TEXCOORD{i}" for i in range(7)})
TEX_FORMATS = {0: "I4", 1: "I8", 2: "IA4", 3: "IA8", 4: "RGB565", 5: "RGB5A3", 6: "RGBA8", 8: "C4", 9: "C8", 10: "C14X2", 14: "CMPR"}
WRAP = {0: "clamp", 1: "repeat", 2: "mirror"}
VTX1_SLOTS = [POS, NRM, NBT, CLR0, CLR1] + [TEX0 + i for i in range(8)]  # VTX1 header order
BLOCK_ORDER = ["INF1", "VTX1", "EVP1", "DRW1", "JNT1", "SHP1", "MAT3", "MDL3", "TEX1"]


def align(n, a=32):
    return (n + a - 1) // a * a


def u8(b, o):
    return b[o]


def u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def s16(b, o):
    return struct.unpack_from(">h", b, o)[0]


def u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def f32(b, o):
    return struct.unpack_from(">f", b, o)[0]


class J3DError(ValueError):
    pass


def check(cond, msg):
    if not cond:
        raise J3DError(msg)


# --- archives ---------------------------------------------------------------------------------


def load_model_bytes(path: Path):
    """(model bytes, archive or None, entry index or None, file name) from a model or .arc file."""
    raw = Path(path).read_bytes()
    from collect_pipeline_seed_inputs import decompress
    data = decompress(raw)
    if data[:4] == b"J3D2":
        return data, None, None, Path(path).name
    if data[:4] != b"RARC":
        raise J3DError(f"{path}: neither a J3D model nor a RARC archive")
    from stage_edit import Archive
    arc = Archive(raw)
    models = [(p, i) for p, i in arc.files.items() if p.endswith((".bdl", ".bmd"))]
    check(models, f"{path}: archive contains no .bdl/.bmd")
    stem = Path(path).stem.lower()
    models.sort(key=lambda m: (Path(m[0]).stem != stem, m[0]))  # <ArcName>.bdl is the actor's model
    p, i = models[0]
    return arc.contents[i], arc, i, p.rsplit("/", 1)[-1]


# --- name tables ------------------------------------------------------------------------------


def read_names(b: bytes, off: int):
    count = u16(b, off)
    names = []
    for i in range(count):
        so = u16(b, off + 4 + i * 4 + 2)
        end = b.index(b"\0", off + so)
        names.append(b[off + so:end].decode("latin-1"))
    return names


def name_key(name: str) -> int:
    k = 0
    for c in name.encode("latin-1"):
        k = (k * 3 + c) & 0xFFFF
    return k


def make_names(names) -> bytes:
    out = bytearray(struct.pack(">HH", len(names), 0xFFFF))
    strings = bytearray()
    base = 4 + 4 * len(names)
    for n in names:
        out += struct.pack(">HH", name_key(n), base + len(strings))
        strings += n.encode("latin-1") + b"\0"
    return bytes(out + strings)


# --- reading ----------------------------------------------------------------------------------


@dataclass
class Part:
    material: int
    positions: np.ndarray
    normals: Optional[np.ndarray]
    uvs: Optional[np.ndarray]
    triangles: np.ndarray
    colors: Optional[np.ndarray] = None

    def validate(self):
        self.positions = np.asarray(self.positions, dtype=np.float64).reshape(-1, 3)
        n = len(self.positions)
        self.triangles = np.asarray(self.triangles, dtype=np.int64).reshape(-1, 3)
        if self.normals is not None:
            self.normals = np.asarray(self.normals, dtype=np.float64).reshape(-1, 3)
            check(len(self.normals) == n, "normals and positions differ in length")
        if self.uvs is not None:
            self.uvs = np.asarray(self.uvs, dtype=np.float64).reshape(-1, 2)
            check(len(self.uvs) == n, "uvs and positions differ in length")
        if self.colors is not None:
            self.colors = np.clip(np.asarray(self.colors), 0, 255).astype(np.uint8).reshape(-1, 4)
            check(len(self.colors) == n, "colors and positions differ in length")
        if len(self.triangles):
            check(self.triangles.min() >= 0 and self.triangles.max() < n, "triangle index out of range")
        check(np.all(np.isfinite(self.positions)), "non-finite position")


class Model:
    """A parsed J3D2 model file (big-endian, as stored on disc)."""

    def __init__(self, data: bytes):
        self.data = bytes(data)
        check(len(data) >= 0x20 and data[:4] == b"J3D2", "not a J3D2 file")
        self.kind = data[4:8].decode("latin-1")
        check(self.kind in ("bdl4", "bdl3", "bmd3", "bmd2"), f"unsupported J3D type {self.kind}")
        check(u32(data, 8) == len(data), f"header size {u32(data, 8)} != file size {len(data)}")
        self.header_tail = data[0x10:0x20]
        self.blocks = {}
        self.block_list = []
        off = 0x20
        for _ in range(u32(data, 12)):
            check(off + 8 <= len(data), "block header outside file")
            tag = data[off:off + 4].decode("latin-1")
            size = u32(data, off + 4)
            check(8 <= size <= len(data) - off, f"{tag}: bad block size")
            self.blocks[tag] = data[off:off + size]
            self.block_list.append(tag)
            off += size
        for tag in ("INF1", "VTX1", "JNT1", "SHP1", "MAT3", "TEX1"):
            check(tag in self.blocks, f"missing {tag} block")
        self._inf1()
        self._vtx1()
        self._shp1()
        self._mat3()
        self._tex1()
        self._jnt1()

    # INF1 -------------------------------------------------------------------------------------
    def _inf1(self):
        b = self.blocks["INF1"]
        self.inf_flags = u16(b, 8)
        self.packet_num = u32(b, 0x0C)
        self.vtx_num = u32(b, 0x10)
        o = u32(b, 0x14)
        self.hierarchy = []
        while True:
            t, v = u16(b, o), u16(b, o + 2)
            self.hierarchy.append((t, v))
            o += 4
            if t == 0:
                break
        # shape -> material, as J3DJointTree::makeHierarchy assigns them
        # (makeHierarchy gives a shape its joint's most recently added material, whatever
        # the nesting.)
        self.shape_material = {}
        self.material_order = []
        cur_mat = None
        for t, v in self.hierarchy:
            if t == 0x11:
                cur_mat = v
                self.material_order.append(v)
            elif t == 0x12:
                self.shape_material[v] = cur_mat

    # VTX1 -------------------------------------------------------------------------------------
    def _vtx1(self):
        b = self.blocks["VTX1"]
        fo = u32(b, 8)
        self.vtx_fmt = {}
        o = fo
        while True:
            attr = u32(b, o)
            if attr == NULL_ATTR:
                break
            self.vtx_fmt[attr] = (u32(b, o + 4), u32(b, o + 8), b[o + 12])
            o += 16
        offs = {VTX1_SLOTS[i]: u32(b, 0x0C + i * 4) for i in range(13)}
        allo = sorted(set([fo] + [x for x in offs.values() if x]))
        self.arrays = {}
        for attr, ao in offs.items():
            if not ao:
                continue
            end = next((x for x in allo if x > ao), len(b))
            cnt, typ, frac = self.vtx_fmt.get(attr if attr != NBT else NRM, (0, 0, 0))
            if attr in (CLR0, CLR1):
                check(typ == RGBA8 or typ in (1, 2), f"{ATTR_NAMES[attr]}: unsupported color type {typ}")
                if typ == RGBA8 or typ == 2:
                    arr = np.frombuffer(b[ao:ao + (end - ao) // 4 * 4], dtype=np.uint8).reshape(-1, 4).copy()
                    if typ == 2:
                        arr[:, 3] = 255
                else:
                    a3 = np.frombuffer(b[ao:ao + (end - ao) // 3 * 3], dtype=np.uint8).reshape(-1, 3)
                    arr = np.concatenate([a3, np.full((len(a3), 1), 255, np.uint8)], 1)
            else:
                ncomp = {POS: 2 + cnt, NRM: 3, NBT: 9}.get(attr, 1 + cnt)
                if attr == NRM and cnt != 0:
                    ncomp = 9 if cnt == 1 else 3
                dt = {0: ">u1", 1: ">i1", 2: ">u2", 3: ">i2", 4: ">f4"}[typ]
                es = COMP_SIZE[typ] * ncomp
                raw = np.frombuffer(b[ao:ao + (end - ao) // es * es], dtype=dt).reshape(-1, ncomp).astype(np.float64)
                if typ != F32:
                    raw = raw / float(1 << frac)
                arr = raw
            self.arrays[attr] = arr
        self.vtx_offsets = offs

    # SHP1 -------------------------------------------------------------------------------------
    def _shp1(self):
        b = self.blocks["SHP1"]
        n = u16(b, 8)
        init, idx, nameo, vdo, mto, dlo, mio, dio = (u32(b, 0x0C + 4 * i) for i in range(8))
        self.shape_names = read_names(b, nameo) if nameo else None
        self.shapes = []
        for s in range(n):
            si = u16(b, idx + 2 * s)
            r = init + si * 0x28
            mtx_type = b[r]
            groups = u16(b, r + 2)
            vd_index, mi_index, di_index = u16(b, r + 4), u16(b, r + 6), u16(b, r + 8)
            radius = f32(b, r + 0x0C)
            bmin = [f32(b, r + 0x10 + 4 * k) for k in range(3)]
            bmax = [f32(b, r + 0x1C + 4 * k) for k in range(3)]
            desc = []
            o = vdo + vd_index
            while True:
                attr, typ = u32(b, o), u32(b, o + 4)
                if attr == NULL_ATTR:
                    break
                desc.append((attr, typ))
                o += 8
            packets = []
            for g in range(groups):
                mo = mio + (mi_index + g) * 8
                use, count, first = u16(b, mo), u16(b, mo + 2), u32(b, mo + 4)
                table = [u16(b, mto + 2 * (first + k)) for k in range(count)]
                do = dio + (di_index + g) * 8
                size, dl_off = u32(b, do), u32(b, do + 4)
                check(dlo + dl_off + size <= len(b), f"shape {s}: display list outside SHP1")
                packets.append(dict(use=use, table=table, dl=b[dlo + dl_off:dlo + dl_off + size]))
            self.shapes.append(dict(mtx_type=mtx_type, desc=desc, packets=packets, radius=radius, min=bmin, max=bmax))

    def vertex_layout(self, desc):
        """[(attr, kind, size)] in GX vertex order for a vertex descriptor list."""
        layout = []
        for attr, typ in sorted(desc):
            if typ == NONE:
                continue
            if attr <= 8:
                size = 1
            elif typ == INDEX8:
                size = 1
            elif typ == INDEX16:
                size = 2
            else:
                cnt, ctype, _ = self.vtx_fmt.get(attr, (1, F32, 0))
                if attr in (CLR0, CLR1):
                    size = COLOR_SIZE[ctype]
                else:
                    ncomp = {POS: 2 + cnt, NRM: 3 if cnt == 0 else 9}.get(attr, 1 + cnt)
                    size = COMP_SIZE[ctype] * ncomp
            layout.append((attr, typ, size))
        return layout

    def decode_dl(self, dl: bytes, layout):
        """[(prim, [vertex dict attr -> value])] from a display list."""
        out = []
        p = 0
        vsize = sum(s for _, _, s in layout)
        while p < len(dl):
            op = dl[p]
            if op == 0x00:
                p += 1
            elif op & 0xF8 in PRIMS:
                prim = op & 0xF8
                check(op & 7 == 0, f"draw with vertex format {op & 7} (J3D uses GX_VTXFMT0)")
                count = u16(dl, p + 1)
                p += 3
                check(p + count * vsize <= len(dl), "draw command runs past the display list")
                verts = []
                for _ in range(count):
                    v = {}
                    for attr, typ, size in layout:
                        if attr <= 8 or typ == INDEX8:
                            v[attr] = dl[p]
                        elif typ == INDEX16:
                            v[attr] = u16(dl, p)
                        else:
                            v[attr] = dl[p:p + size]
                        p += size
                    verts.append(v)
                out.append((prim, verts))
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
                raise J3DError(f"unknown display list opcode 0x{op:02X} at {p}")
        return out

    def shape_triangles(self, s):
        """Triangles of shape s as lists of three vertex dicts, front faces in GX order."""
        sh = self.shapes[s]
        layout = self.vertex_layout(sh["desc"])
        tris = []
        for pk in sh["packets"]:
            for prim, verts in self.decode_dl(pk["dl"], layout):
                if prim == 0x90:
                    tris += [verts[i:i + 3] for i in range(0, len(verts) - 2, 3)]
                elif prim == 0x98:
                    for i in range(len(verts) - 2):
                        a, b_, c = verts[i], verts[i + 1], verts[i + 2]
                        tris.append([a, b_, c] if i % 2 == 0 else [b_, a, c])
                elif prim == 0xA0:
                    for i in range(1, len(verts) - 1):
                        tris.append([verts[0], verts[i], verts[i + 1]])
                elif prim == 0x80:
                    for i in range(0, len(verts) - 3, 4):
                        q = verts[i:i + 4]
                        tris += [[q[0], q[1], q[2]], [q[0], q[2], q[3]]]
        return tris

    # MAT3 -------------------------------------------------------------------------------------
    def _mat3(self):
        b = self.blocks["MAT3"]
        self.mat_num = u16(b, 8)
        self.mat_names = read_names(b, u32(b, 0x14)) if u32(b, 0x14) else [f"mat{i}" for i in range(self.mat_num)]
        self.mat_offs = {name: u32(b, off) for name, off in (
            ("init", 0x0C), ("id", 0x10), ("ind", 0x18), ("cull", 0x1C), ("matcolor", 0x20), ("chnum", 0x24),
            ("chinfo", 0x28), ("amb", 0x2C), ("light", 0x30), ("tgnum", 0x34), ("texcoord", 0x38),
            ("texcoord2", 0x3C), ("texmtx", 0x40), ("postmtx", 0x44), ("texno", 0x48), ("tevorder", 0x4C),
            ("tevcolor", 0x50), ("kcolor", 0x54), ("tevnum", 0x58), ("tevstage", 0x5C), ("swap", 0x60),
            ("swaptab", 0x64), ("fog", 0x68), ("alphacmp", 0x6C), ("blend", 0x70), ("zmode", 0x74),
            ("zcomp", 0x78), ("dither", 0x7C), ("nbt", 0x80))}

    def material(self, m):
        """A summary of material m (see `info`)."""
        b, o = self.blocks["MAT3"], self.mat_offs
        r = o["init"] + u16(b, o["id"] + 2 * m) * 0x14C
        info = dict(name=self.mat_names[m], mode=b[r])

        def tab(key, idx, size):
            return None if idx in (0xFF, 0xFFFF) or not o[key] else b[o[key] + idx * size:o[key] + (idx + 1) * size]

        cull = tab("cull", b[r + 1], 4)
        info["cull"] = {0: "none", 1: "front", 2: "back", 3: "all"}.get(u32(cull, 0)) if cull else None
        chnum = tab("chnum", b[r + 2], 1)
        info["chan_num"] = chnum[0] if chnum else 0
        chans = []
        for c in range(4):
            e = tab("chinfo", u16(b, r + 0x0C + 2 * c), 8)
            if e:
                chans.append(dict(light=bool(e[0]), mat_src="vtx" if e[1] else "reg", amb_src="vtx" if e[5] else "reg", mask=e[2]))
            else:
                chans.append(None)
        info["chans"] = chans
        mc = [tab("matcolor", u16(b, r + 8 + 2 * k), 4) for k in range(2)]
        info["mat_color"] = [tuple(x) if x else None for x in mc]
        tg = tab("tgnum", b[r + 3], 1)
        info["texgen_num"] = tg[0] if tg else 0
        texgens = []
        for k in range(info["texgen_num"]):
            e = tab("texcoord", u16(b, r + 0x28 + 2 * k), 4)
            texgens.append(dict(type=e[0], src=e[1], mtx=e[2]) if e else None)
        info["texgens"] = texgens
        texmtx = []
        for k in range(10):
            e = tab("texmtx", u16(b, r + 0x48 + 2 * k), 0x64)
            if e:
                texmtx.append(dict(slot=k, proj=e[0], kind=e[1] & 0x3F, scale=(f32(e, 0x10), f32(e, 0x14)),
                                   rot=s16(e, 0x18), trans=(f32(e, 0x1C), f32(e, 0x20))))
        info["texmtx"] = texmtx
        texnames = self.tex_names if hasattr(self, "tex_names") else []
        textures = []
        for k in range(8):
            e = tab("texno", u16(b, r + 0x84 + 2 * k), 2)
            if e:
                t = u16(e, 0)
                textures.append((k, t, texnames[t] if t < len(texnames) else "?"))
        info["textures"] = textures
        tn = tab("tevnum", b[r + 4], 1)
        info["tev_num"] = tn[0] if tn else 0
        uses_ras = False
        orders = []
        for k in range(info["tev_num"]):
            od = tab("tevorder", u16(b, r + 0xBC + 2 * k), 4)
            st = tab("tevstage", u16(b, r + 0xE4 + 2 * k), 20)
            orders.append(tuple(od[:3]) if od else None)
            if st and (any(x in (10, 11) for x in st[1:5]) or 5 in st[10:14]):
                uses_ras = True
        info["tev_orders"] = orders
        info["tev_uses_raster"] = uses_ras
        bl = tab("blend", u16(b, r + 0x148), 4)
        info["blend"] = tuple(bl) if bl else None
        ac = tab("alphacmp", u16(b, r + 0x146), 8)
        info["alpha_cmp"] = tuple(ac[:5]) if ac else None
        ind = o["ind"] and b[o["ind"] + m * 0x138] if o["ind"] and o["ind"] + (m + 1) * 0x138 <= len(b) else 0
        info["indirect"] = bool(ind)
        return info

    def material_needs(self, m):
        """Vertex attributes material m's channels and texgens read."""
        info = self.material(m)
        needs = {POS}
        lit = False
        for c in info["chans"][:max(1, info["chan_num"]) * 2]:
            if c is None:
                continue
            if c["light"]:
                lit = True
                needs.add(NRM)
            if c["mat_src"] == "vtx" or (c["light"] and c["amb_src"] == "vtx"):
                needs.add(CLR0)
        for tg in info["texgens"]:
            if tg is None:
                continue
            if 4 <= tg["src"] <= 11:
                needs.add(TEX0 + tg["src"] - 4)
            elif tg["src"] in (1, 2, 3):
                needs.add(NRM)
        return needs, lit, info

    # TEX1 / JNT1 --------------------------------------------------------------------------------
    def _tex1(self):
        b = self.blocks["TEX1"]
        n = u16(b, 8)
        to, no = u32(b, 0x0C), u32(b, 0x10)
        self.tex_names = read_names(b, no) if no else [f"tex{i}" for i in range(n)]
        self.textures = []
        for i in range(n):
            r = to + i * 0x20
            self.textures.append(dict(name=self.tex_names[i], fmt=TEX_FORMATS.get(b[r], b[r]), w=u16(b, r + 2), h=u16(b, r + 4),
                                      wrap=(WRAP.get(b[r + 6]), WRAP.get(b[r + 7])), mips=b[r + 0x18]))

    def _jnt1(self):
        b = self.blocks["JNT1"]
        n = u16(b, 8)
        init, idx, no = u32(b, 0x0C), u32(b, 0x10), u32(b, 0x14)
        self.joint_names = read_names(b, no) if no else [f"joint{i}" for i in range(n)]
        self.joints = []
        for j in range(n):
            r = init + u16(b, idx + 2 * j) * 0x40
            self.joints.append(dict(kind=u16(b, r), radius=f32(b, r + 0x24), min=[f32(b, r + 0x28 + 4 * k) for k in range(3)],
                                    max=[f32(b, r + 0x34 + 4 * k) for k in range(3)],
                                    scale=[f32(b, r + 4 + 4 * k) for k in range(3)], trans=[f32(b, r + 0x18 + 4 * k) for k in range(3)]))


# --- extracting geometry ----------------------------------------------------------------------


def extract_parts(model: Model):
    """One Part per shape of a model (single-joint view: joint transforms are ignored).

    Triangles come out counter-clockwise (front faces as in OBJ/Blender); uvs are TEX0 as
    stored (t grows downwards in the texture); colors are CLR0 when the shape has them."""
    P = model.arrays[POS]
    N = model.arrays.get(NRM)
    C = model.arrays.get(CLR0)
    T = model.arrays.get(TEX0)
    parts = []
    for s in range(len(model.shapes)):
        keys, tris = {}, []
        for tri in model.shape_triangles(s):
            row = []
            for v in tri:
                key = (v.get(POS), v.get(NRM), v.get(CLR0), v.get(TEX0))
                row.append(keys.setdefault(key, len(keys)))
            tris.append((row[0], row[2], row[1]))  # GX clockwise -> counter-clockwise
        ks = list(keys)
        pos = np.array([P[k[0]] for k in ks]).reshape(-1, 3)
        nrm = np.array([N[k[1]] for k in ks]).reshape(-1, 3) if N is not None and ks and ks[0][1] is not None else None
        col = np.array([C[k[2]] for k in ks]).reshape(-1, 4).astype(np.uint8) if C is not None and ks and ks[0][2] is not None else None
        uv = np.array([T[k[3]][:2] for k in ks]).reshape(-1, 2) if T is not None and ks and ks[0][3] is not None else None
        mat = model.shape_material.get(s, 0)
        parts.append(Part(mat, pos, nrm, uv, np.array(tris, dtype=np.int64).reshape(-1, 3), col))
    return parts


# --- writing ----------------------------------------------------------------------------------

PAD = b"This is padding data to align"


def pad_to(buf: bytearray, a=32):
    n = -len(buf) % a
    buf += (PAD * 2)[:n]
    return buf


def finish_block(tag: str, body: bytearray) -> bytes:
    pad_to(body)
    struct.pack_into(">4sI", body, 0, tag.encode(), len(body))
    return bytes(body)


def smooth_normals(pos, tris):
    """Area-weighted vertex normals for counter-clockwise triangles, shared across
    vertices at the same position."""
    _, inv = np.unique(pos.round(4), axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    a, b, c = pos[tris[:, 0]], pos[tris[:, 1]], pos[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    acc = np.zeros((inv.max() + 1 if len(inv) else 0, 3))
    for k in range(3):
        np.add.at(acc, inv[tris[:, k]], fn)
    n = acc[inv]
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = np.where(ln > 1e-12, n / np.maximum(ln, 1e-12), np.array([0.0, 1.0, 0.0]))
    return n


def _dedupe(rows: np.ndarray):
    """(unique rows, index per input row) keeping first-occurrence order."""
    if len(rows) == 0:
        return rows, np.zeros(0, dtype=np.int64)
    view = np.ascontiguousarray(rows).view(np.dtype((np.void, rows.dtype.itemsize * rows.shape[1]))).reshape(-1)
    _, first, inv = np.unique(view, return_index=True, return_inverse=True)
    order = np.argsort(first)
    remap = np.empty_like(order)
    remap[order] = np.arange(len(order))
    return rows[first[order]], remap[inv.reshape(-1)]


def build_model(template: bytes, parts, name: Optional[str] = None, fmt: Optional[str] = None) -> bytes:
    """A J3D model with the template's materials/textures and the parts' geometry.

    parts: list of Part; several parts with the same material are merged into one shape.
    name: the root joint's name (default: the template's root joint name).
    fmt: None (template's type), 'bdl' or 'bmd' ('bmd' drops MDL3)."""
    t = Model(template)
    nmat = t.mat_num
    for p in parts:
        p.validate()
        check(0 <= p.material < nmat, f"material {p.material} out of range (template has {nmat})")
    kind = t.kind
    if fmt == "bmd":
        kind = "bmd3"
    elif fmt == "bdl":
        kind = "bdl4"
    elif fmt is not None:
        raise J3DError("fmt must be 'bdl' or 'bmd'")
    keep_mdl3 = kind.startswith("bdl") and "MDL3" in t.blocks

    # vertex descriptor per material, from the template shape drawn with it
    mat_desc = {}
    for s, m in t.shape_material.items():
        if m is not None and m not in mat_desc:
            mat_desc[m] = (t.shapes[s]["desc"], s)
    descs = []
    for m in range(nmat):
        if m in mat_desc:
            desc, s = mat_desc[m]
            out = []
            const = {}
            for attr, typ in sorted(desc):
                if typ == NONE:
                    continue
                check(attr != NBT, f"material {m} ({t.mat_names[m]}): NBT vertex data is not supported")
                if attr == PNMTXIDX:
                    out.append((attr, DIRECT))
                    const[attr] = 0
                elif attr <= 8:
                    tris = t.shape_triangles(s)
                    const[attr] = tris[0][0].get(attr, 60) if tris else 60
                    out.append((attr, DIRECT))
                else:
                    out.append((attr, INDEX16))
        else:
            needs, _, _ = t.material_needs(m)
            out, const = [(a, INDEX16) for a in sorted(needs | {POS})], {}
        descs.append((out, const))
    used_attrs = {a for d, _ in descs for a, _ in d if a >= POS}

    # Default vertex color per material: the mean CLR0 of the template's shape for it. The
    # "_v" planet materials take their (baked) shading from CLR0, so white would look flat
    # and over-bright.
    default_color = {}
    if CLR0 in t.arrays:
        for s, m in t.shape_material.items():
            if m in default_color or m is None:
                continue
            idx = [v[CLR0] for tri in t.shape_triangles(s) for v in tri if CLR0 in v]
            if idx:
                default_color[m] = np.round(t.arrays[CLR0][idx].mean(0)).astype(np.uint8)

    # merge parts per material; fill in missing attributes
    merged = {}
    for p in parts:
        n = len(p.positions)
        nrm = p.normals if p.normals is not None else smooth_normals(p.positions, p.triangles)
        uv = p.uvs if p.uvs is not None else np.zeros((n, 2))
        col = p.colors if p.colors is not None else np.tile(default_color.get(p.material, np.full(4, 255, np.uint8)), (n, 1))
        g = merged.setdefault(p.material, dict(pos=[], nrm=[], uv=[], col=[], tris=[], n=0))
        g["pos"].append(p.positions)
        g["nrm"].append(nrm)
        g["uv"].append(uv)
        g["col"].append(col)
        g["tris"].append(p.triangles + g["n"])
        g["n"] += n

    # global arrays (de-duplicated) and per-material index rows
    allpos, allnrm, alluv, allcol = [], [], [], []
    for m in sorted(merged):
        g = merged[m]
        allpos += g["pos"]
        allnrm += g["nrm"]
        alluv += g["uv"]
        allcol += g["col"]
    if allpos:
        P = np.concatenate(allpos).astype(">f4")
        Nn = np.concatenate(allnrm)  # given normals are kept as they are (not re-normalised)
        check(np.all(np.isfinite(Nn)), "non-finite normal")
        Nq = np.clip(np.round(Nn * 16384.0), -32768, 32767).astype(">i2")
        UV = np.concatenate(alluv).astype(">f4")
        CO = np.concatenate(allcol).astype(np.uint8)
    else:  # no geometry at all: one dummy vertex so the degenerate shapes have something to index
        P = np.zeros((1, 3), ">f4")
        Nq = np.array([[0, 16384, 0]], ">i2")
        UV = np.zeros((1, 2), ">f4")
        CO = np.full((1, 4), 255, np.uint8)
    P_u, P_i = _dedupe(P)
    N_u, N_i = _dedupe(Nq)
    T_u, T_i = _dedupe(UV)
    C_u, C_i = _dedupe(CO)
    for name_, arr in (("positions", P_u), ("normals", N_u), ("uvs", T_u), ("colors", C_u)):
        check(len(arr) <= 0xFFFF, f"too many unique {name_} ({len(arr)}; GX_INDEX16 allows 65535)")

    # VTX1 ----------------------------------------------------------------------------------------
    arrays = {POS: (1, F32, 0, P_u.tobytes())}
    if NRM in used_attrs:
        arrays[NRM] = (0, S16, 14, N_u.tobytes())
    for a in (CLR0, CLR1):
        if a in used_attrs:
            arrays[a] = (1, RGBA8, 0, C_u.tobytes())
    for k in range(8):
        if TEX0 + k in used_attrs:
            arrays[TEX0 + k] = (1, F32, 0, T_u.tobytes())
    vtx = bytearray(0x40)
    struct.pack_into(">I", vtx, 8, 0x40)
    for a in sorted(arrays):
        cnt, typ, frac, _ = arrays[a]
        vtx += struct.pack(">IIIB3s", a, cnt, typ, frac, b"\xff" * 3)
    vtx += struct.pack(">IIIB3s", NULL_ATTR, 1, 0, 0, b"\xff" * 3)
    for a in sorted(arrays):
        pad_to(vtx)
        struct.pack_into(">I", vtx, 0x0C + 4 * VTX1_SLOTS.index(a), len(vtx))
        vtx += arrays[a][3]
    vtx1 = finish_block("VTX1", vtx)

    # shapes ------------------------------------------------------------------------------------
    offsets = {}  # material -> row offset into the concatenated vertex rows
    o = 0
    for m in sorted(merged):
        offsets[m] = o
        o += merged[m]["n"]
    shapes = []
    for m in range(nmat):
        desc, const = descs[m]
        if m in merged:
            g = merged[m]
            tris = np.concatenate(g["tris"])
            rows = tris[:, [0, 2, 1]].reshape(-1) + offsets[m]  # counter-clockwise -> GX clockwise
            pts = P_u[P_i[np.unique(rows)]].astype(np.float64)
        else:
            rows = np.zeros(3, dtype=np.int64)  # one degenerate triangle: the material needs a shape
            pts = P_u[P_i[:1]].astype(np.float64) if len(P_i) else np.zeros((1, 3))
        cols = []
        for attr, typ in desc:
            if typ == DIRECT:
                cols.append(np.full((len(rows), 1), const.get(attr, 0), dtype=">u1").view(np.uint8))
            else:
                src = {POS: P_i, NRM: N_i, CLR0: C_i, CLR1: C_i}.get(attr, T_i)
                cols.append(src[rows].astype(">u2").reshape(-1, 1).view(np.uint8))
        vbytes = np.concatenate(cols, axis=1) if cols else np.zeros((len(rows), 0), np.uint8)
        dl = bytearray()
        per = 0xFFFF // 3 * 3
        for start in range(0, len(rows), per):
            chunk = vbytes[start:start + per]
            dl += struct.pack(">BH", TRIANGLES, len(chunk)) + chunk.tobytes()
        dl += bytes(-len(dl) % 32)
        mn, mx = pts.min(0), pts.max(0)
        radius = float(np.linalg.norm(pts, axis=1).max())
        shapes.append(dict(desc=desc, dl=bytes(dl), min=mn, max=mx, radius=radius))

    shp = bytearray(0x2C)
    struct.pack_into(">HH", shp, 8, nmat, 0xFFFF)
    desc_blobs, desc_index = [], []
    for sh in shapes:
        blob = b"".join(struct.pack(">II", a, ty) for a, ty in sh["desc"]) + struct.pack(">II", NULL_ATTR, 0)
        if blob not in desc_blobs:
            desc_blobs.append(blob)
        desc_index.append(sum(len(b) for b in desc_blobs[:desc_blobs.index(blob)]))
    struct.pack_into(">I", shp, 0x0C, len(shp))
    for i, sh in enumerate(shapes):
        shp += struct.pack(">BBHHHHH", 0, 0xFF, 1, desc_index[i], i, i, 0xFFFF)
        shp += struct.pack(">f3f3f", sh["radius"], *sh["min"], *sh["max"])
    struct.pack_into(">I", shp, 0x10, len(shp))
    for i in range(nmat):
        shp += struct.pack(">H", i)
    pad_to(shp, 4)
    struct.pack_into(">I", shp, 0x18, len(shp))
    for blob in desc_blobs:
        shp += blob
    struct.pack_into(">I", shp, 0x1C, len(shp))
    shp += struct.pack(">H", 0)  # matrix table: draw matrix 0
    pad_to(shp)
    struct.pack_into(">I", shp, 0x20, len(shp))
    dl_base = len(shp)
    dl_offs = []
    for sh in shapes:
        dl_offs.append(len(shp) - dl_base)
        shp += sh["dl"]
    struct.pack_into(">I", shp, 0x24, len(shp))
    for i in range(nmat):
        shp += struct.pack(">HHI", 0, 1, 0)
    struct.pack_into(">I", shp, 0x28, len(shp))
    for i, sh in enumerate(shapes):
        shp += struct.pack(">II", len(sh["dl"]), dl_offs[i])
    shp1 = finish_block("SHP1", shp)

    # bounds -----------------------------------------------------------------------------------
    real = [sh for m, sh in enumerate(shapes) if m in merged] or shapes
    bmin = np.min([sh["min"] for sh in real], axis=0)
    bmax = np.max([sh["max"] for sh in real], axis=0)
    brad = max(sh["radius"] for sh in real)

    # JNT1 (one root joint, identity transform; flags copied from the template's root) ----------
    tj = t.blocks["JNT1"]
    rec = bytearray(tj[u32(tj, 0x0C) + u16(tj, u32(tj, 0x10)) * 0x40:][:0x40])
    struct.pack_into(">3f3hH3f", rec, 4, 1.0, 1.0, 1.0, 0, 0, 0, 0xFFFF, 0.0, 0.0, 0.0)
    struct.pack_into(">f3f3f", rec, 0x24, brad, *bmin, *bmax)
    jnt = bytearray(0x18)
    struct.pack_into(">HHI", jnt, 8, 1, 0xFFFF, 0x18)
    jnt += rec
    struct.pack_into(">I", jnt, 0x10, len(jnt))
    jnt += struct.pack(">H", 0)
    pad_to(jnt, 4)
    struct.pack_into(">I", jnt, 0x14, len(jnt))
    jnt += make_names([name or t.joint_names[0]])
    jnt1 = finish_block("JNT1", jnt)

    # EVP1 / DRW1 ------------------------------------------------------------------------------
    evp = bytearray(0x1C)
    struct.pack_into(">HH", evp, 8, 0, 0xFFFF)
    evp1 = finish_block("EVP1", evp)
    drw = bytearray(0x14)
    struct.pack_into(">HHII", drw, 8, 1, 0xFFFF, 0x14, 0x16)
    drw += struct.pack(">BBH", 0, 0, 0)  # flag[0] (0 = joint matrix) at 0x14, pad, index[0] (joint 0) at 0x16
    drw1 = finish_block("DRW1", drw)

    # INF1 -------------------------------------------------------------------------------------
    order = [m for m in t.material_order if m < nmat]
    order = list(dict.fromkeys(order)) + [m for m in range(nmat) if m not in order]
    hier = [(0x10, 0), (0x01, 0)]
    for m in order:
        hier += [(0x11, m), (0x01, 0), (0x12, m), (0x02, 0)]
    hier += [(0x02, 0), (0x00, 0)]
    inf = bytearray(0x18)
    struct.pack_into(">HHIII", inf, 8, t.inf_flags, 0xFFFF, nmat, len(P_u), 0x18)
    for ty, v in hier:
        inf += struct.pack(">HH", ty, v)
    inf1 = finish_block("INF1", inf)

    new = {"INF1": inf1, "VTX1": vtx1, "EVP1": evp1, "DRW1": drw1, "JNT1": jnt1, "SHP1": shp1}
    blocks = []
    for tag in t.block_list:
        if tag in new:
            blocks.append(new.pop(tag))
        elif tag == "MDL3" and not keep_mdl3:
            continue
        elif tag in ("MAT3", "MDL3", "TEX1"):
            blocks.append(t.blocks[tag])
        else:
            raise J3DError(f"template block {tag} is not supported")
    check(not new, f"template lacks blocks {sorted(new)}")
    body = b"".join(blocks)
    head = struct.pack(">4s4sII", b"J3D2", kind.encode(), 0x20 + len(body), len(blocks)) + t.header_tail
    return head + body


# --- validation -------------------------------------------------------------------------------


def validate(data: bytes):
    """Structural checks the game's loader relies on; returns (model, list of notes)."""
    m = Model(data)
    notes = []
    off = 0x20
    for tag in m.block_list:
        size = len(m.blocks[tag])
        if size % 32:
            notes.append(f"{tag}: size {size} not 32-byte aligned")
        check(tag in BLOCK_ORDER, f"{tag}: block type the native loader rejects")
        off += size
    check(off == len(data), "blocks do not fill the file")
    nj, ns, nm = len(m.joints), len(m.shapes), m.mat_num
    drw = m.blocks.get("DRW1")
    ndrw = u16(drw, 8) if drw else 0
    if drw:
        for i in range(ndrw):
            flag, idx = drw[u32(drw, 0x0C) + i], u16(drw, u32(drw, 0x10) + 2 * i)
            check(flag != 0 or idx < nj, f"DRW1 entry {i} joint {idx} out of range")
    seen_mat, seen_shape = [], []
    for ty, v in m.hierarchy:
        if ty == 0x10:
            check(v < nj, f"hierarchy joint {v} out of range")
        elif ty == 0x11:
            check(v < nm, f"hierarchy material {v} out of range")
            seen_mat.append(v)
        elif ty == 0x12:
            check(v < ns, f"hierarchy shape {v} out of range")
            seen_shape.append(v)
    check(sorted(seen_shape) == list(range(ns)), "every shape must appear once in the hierarchy")
    if sorted(seen_mat) != list(range(nm)):
        notes.append("not every material appears exactly once in the hierarchy (unused materials have no shape)")
    counts = {a: len(arr) for a, arr in m.arrays.items()}
    if POS in counts and m.vtx_fmt[POS][1] != F32:
        counts[POS] = m.vtx_num  # padding after s16 arrays reads as extra entries
    prims = 0
    for s, sh in enumerate(m.shapes):
        for pk in sh["packets"]:
            check(pk["use"] < max(ndrw, 1) or sh["mtx_type"] == 3, f"shape {s}: draw matrix {pk['use']} out of range")
            for i in pk["table"]:
                check(i == 0xFFFF or i < max(ndrw, 1), f"shape {s}: matrix table entry {i} out of range")
            layout = m.vertex_layout(sh["desc"])
            for attr, typ, _ in layout:
                check(attr <= 8 or attr in m.arrays, f"shape {s}: {ATTR_NAMES.get(attr, attr)} has no VTX1 array")
            for prim, verts in m.decode_dl(pk["dl"], layout):
                prims += 1
                for v in verts:
                    for attr, typ, _ in layout:
                        if typ in (INDEX8, INDEX16) and attr > 8:
                            check(v[attr] < counts[attr], f"shape {s}: {ATTR_NAMES[attr]} index {v[attr]} >= {counts[attr]}")
    return m, notes, prims


# --- OBJ --------------------------------------------------------------------------------------


def read_obj(path: Path, material_map: dict, scale: float = 1.0, flip_v: bool = True, template: Optional[Model] = None):
    """Parts from a Wavefront OBJ (usemtl groups). material_map: OBJ material name -> template
    material index; unmapped names fall back to a template material of the same name, then
    to a number. Faces are fan-triangulated; OBJ is counter-clockwise like Part."""
    V, VT, VN, VC = [], [], [], []
    groups = {}
    cur = None
    for line in Path(path).read_text(errors="replace").splitlines():
        f = line.split()
        if not f or f[0].startswith("#"):
            continue
        if f[0] == "v":
            V.append([float(x) for x in f[1:4]])
            VC.append([float(x) for x in f[4:7]] if len(f) >= 7 else None)
        elif f[0] == "vt":
            VT.append([float(x) for x in f[1:3]] + ([0.0] if len(f) < 3 else []))
        elif f[0] == "vn":
            VN.append([float(x) for x in f[1:4]])
        elif f[0] == "usemtl":
            cur = " ".join(f[1:])
        elif f[0] == "f":
            idx = []
            for c in f[1:]:
                parts = c.split("/")
                vi = int(parts[0])
                ti = int(parts[1]) if len(parts) > 1 and parts[1] else None
                ni = int(parts[2]) if len(parts) > 2 and parts[2] else None
                fix = lambda i, n: None if i is None else (i - 1 if i > 0 else n + i)
                idx.append((fix(vi, len(V)), fix(ti, len(VT)), fix(ni, len(VN))))
            g = groups.setdefault(cur, [])
            for k in range(1, len(idx) - 1):
                g.append((idx[0], idx[k], idx[k + 1]))
    names = template.mat_names if template else []
    parts = []
    for gname, faces in groups.items():
        if gname in material_map:
            mat = material_map[gname]
        elif gname in names:
            mat = names.index(gname)
        elif gname is not None and gname.isdigit():
            mat = int(gname)
        elif None in material_map or "*" in material_map:
            mat = material_map.get("*", material_map.get(None))
        else:
            raise J3DError(f"OBJ material {gname!r} has no template material (use --materials {gname}=INDEX)")
        keys = {}
        tris = []
        for face in faces:
            tris.append([keys.setdefault(k, len(keys)) for k in face])
        ks = list(keys)
        pos = np.array([V[k[0]] for k in ks], dtype=np.float64) * scale
        has_n = all(k[2] is not None for k in ks)
        has_t = all(k[1] is not None for k in ks)
        nrm = np.array([VN[k[2]] for k in ks]) if has_n else None
        uv = np.array([VT[k[1]][:2] for k in ks]) if has_t else None
        if uv is not None and flip_v:
            uv[:, 1] = 1.0 - uv[:, 1]
        col = None
        if all(VC[k[0]] is not None for k in ks):
            c = np.array([VC[k[0]] for k in ks])
            c = c * 255.0 if c.max() <= 1.0 else c
            col = np.concatenate([np.clip(np.round(c), 0, 255), np.full((len(c), 1), 255)], 1).astype(np.uint8)
        if not has_t:
            print(f"warning: OBJ group {gname!r} has faces without UVs; using (0, 0)", file=sys.stderr)
        parts.append(Part(mat, pos, nrm, uv, np.array(tris, dtype=np.int64), col))
    return parts


# --- reports ----------------------------------------------------------------------------------


def material_report(m: Model):
    lines = []
    shape_of = {}
    for s, mat in m.shape_material.items():
        shape_of.setdefault(mat, s)
    parts = extract_parts(m)
    for i in range(m.mat_num):
        needs, lit, info = m.material_needs(i)
        mode = {1: "opaque", 2: "alpha-test", 4: "translucent"}.get(info["mode"], f"mode {info['mode']}")
        lines.append(f"[{i}] {info['name']}  {mode}, cull {info['cull']}, {info['tev_num']} TEV stage(s)"
                     + (", indirect" if info["indirect"] else ""))
        for k, tno, tname in info["textures"]:
            tx = m.textures[tno] if tno < len(m.textures) else {}
            lines.append(f"     texmap{k}: #{tno} {tname} {tx.get('fmt')} {tx.get('w')}x{tx.get('h')} wrap {tx.get('wrap')}")
        for k, tg in enumerate(info["texgens"]):
            if tg:
                mtx = "identity" if tg["mtx"] == 60 else f"texmtx{(tg['mtx'] - 30) // 3}" if 30 <= tg["mtx"] < 60 else tg["mtx"]
                lines.append(f"     texgen{k}: {TEXGEN_SRC.get(tg['src'], tg['src'])} via {mtx} (type {tg['type']})")
        for tm in info["texmtx"]:
            lines.append(f"     texmtx{tm['slot']}: kind {tm['kind']} scale {tm['scale'][0]:g},{tm['scale'][1]:g} "
                         f"rot {tm['rot']} trans {tm['trans'][0]:g},{tm['trans'][1]:g}")
        ch = []
        for k, c in enumerate(info["chans"][:max(1, info["chan_num"]) * 2]):
            if c:
                ch.append(f"{['color0', 'alpha0', 'color1', 'alpha1'][k]}: {'lit' if c['light'] else 'unlit'} mat={c['mat_src']}"
                          + (f" amb={c['amb_src']}" if c["light"] else ""))
        lines.append("     channels: " + "; ".join(ch) + f"; TEV reads raster color: {info['tev_uses_raster']}")
        lines.append(f"     material needs: {', '.join(ATTR_NAMES[a] for a in sorted(needs))}")
        s = shape_of.get(i)
        if s is not None:
            lines.append(f"     template shape {s} sends: {', '.join(ATTR_NAMES[a] for a, ty in m.shapes[s]['desc'] if ty)}")
            p = parts[s]
            if p.uvs is not None and len(p.triangles):
                a, b, c = (p.positions[p.triangles[:, k]] for k in range(3))
                wa = np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2
                ta, tb, tc = (p.uvs[p.triangles[:, k]] for k in range(3))
                ua = np.abs((tb - ta)[:, 0] * (tc - ta)[:, 1] - (tb - ta)[:, 1] * (tc - ta)[:, 0]).sum() / 2
                dens = math.sqrt(ua / wa) * 1000 if wa > 0 else 0
                lines.append(f"     template UVs: s {p.uvs[:, 0].min():.2f}..{p.uvs[:, 0].max():.2f}, "
                             f"t {p.uvs[:, 1].min():.2f}..{p.uvs[:, 1].max():.2f}; about {dens:.2f} texture repeats per 1000 units")
            if p.colors is not None:
                c = p.colors.astype(int)
                lines.append(f"     template vertex colors: rgb mean {c[:, :3].mean(0).round().astype(int).tolist()}, "
                             f"min {c[:, :3].min(0).tolist()}, max {c[:, :3].max(0).tolist()}, alpha {c[:, 3].min()}..{c[:, 3].max()}")
            lines.append(f"     template triangles: {len(p.triangles)}, bounds {np.round(p.positions.min(0)).astype(int).tolist()}"
                         f"..{np.round(p.positions.max(0)).astype(int).tolist()}")
    return lines


def cmd_info(path):
    data, _, _, fname = load_model_bytes(path)
    m = Model(data)
    print(f"{fname}: J3D2 {m.kind}, blocks {' '.join(m.block_list)}, {len(m.joints)} joint(s), {len(m.shapes)} shape(s), "
          f"{m.mat_num} material(s), {len(m.textures)} texture(s)")
    print("vertex formats: " + ", ".join(f"{ATTR_NAMES[a]} {COMP_NAMES.get(t, t) if a not in (CLR0, CLR1) else 'rgba8' if t == 5 else t}"
                                         + (f" frac {fr}" if fr else "") for a, (c, t, fr) in sorted(m.vtx_fmt.items())))
    print("joints: " + ", ".join(m.joint_names) + f"; root radius {m.joints[0]['radius']:.1f}")
    for line in material_report(m):
        print(line)


def tri_signature(part: Part, tol=1e-3, colors=True):
    """Sorted, rotation-normalised triangle keys (positions, uvs, colors) for comparisons."""
    keys = []
    for tri in part.triangles:
        vs = []
        for k in tri:
            v = tuple(np.round(part.positions[k] / tol).astype(int))
            if part.uvs is not None:
                v += tuple(np.round(part.uvs[k] / tol).astype(int))
            if colors and part.colors is not None:
                v += tuple(int(x) for x in part.colors[k])
            vs.append(v)
        r = vs.index(min(vs))
        keys.append(tuple(vs[r:] + vs[:r]))
    return sorted(keys)


def compare_models(a: Model, b: Model):
    """Per material: identical triangles (positions, uvs, colors) and normals within 2e-3."""
    def collect(model):
        out = {}
        for p in extract_parts(model):
            for tri in p.triangles:
                vs = []
                for k in tri:
                    key = tuple(np.round(p.positions[k] * 1000).astype(int))
                    key += tuple(np.round(p.uvs[k] * 1000).astype(int)) if p.uvs is not None else ()
                    key += tuple(int(x) for x in p.colors[k]) if p.colors is not None else ()
                    vs.append((key, tuple(p.normals[k]) if p.normals is not None else ()))
                r = vs.index(min(vs, key=lambda v: v[0]))
                vs = vs[r:] + vs[:r]
                out.setdefault(p.material, []).append((tuple(v[0] for v in vs), sum((v[1] for v in vs), ())))
        for v in out.values():
            v.sort()
        return out
    ca, cb = collect(a), collect(b)
    problems, total = [], 0
    for mat, ta in ca.items():
        tb = cb.get(mat, [])
        total += len(ta)
        if [x[0] for x in ta] != [x[0] for x in tb]:
            problems.append(f"material {mat}: {len(ta)} vs {len(tb)} triangles, {len(set(ta) ^ set(tb))} differ")
            continue
        if ta and len(ta[0][1]) and len(tb[0][1]):
            worst = float(np.abs(np.array([x[1] for x in ta]) - np.array([x[1] for x in tb])).max())
            if worst > 2e-3:
                problems.append(f"material {mat}: normals differ by up to {worst:.4f}")
    return problems, total


def cmd_check(path):
    data, *_ = load_model_bytes(path)
    m, notes, prims = validate(data)
    print(f"ok: {m.kind}, {len(data)} bytes, blocks {' '.join(m.block_list)}, {len(m.shapes)} shapes, "
          f"{prims} draw commands, {sum(len(m.shape_triangles(s)) for s in range(len(m.shapes)))} triangles")
    for n in notes:
        print("note:", n)


def cmd_roundtrip(path, out=None):
    data, *_ = load_model_bytes(path)
    src = Model(data)
    parts = extract_parts(src)
    built = build_model(data, parts)
    m, notes, _ = validate(built)
    problems, total = compare_models(src, m)
    for blk in ("MAT3", "MDL3", "TEX1"):
        if blk in src.blocks:
            check(m.blocks.get(blk) == src.blocks[blk], f"{blk} changed")
    print(f"{Path(path).name}: {total} triangles in {len(parts)} parts; rebuilt {len(built)} bytes (template {len(data)}); "
          f"MAT3/MDL3/TEX1 identical; " + ("geometry identical" if not problems else "DIFFERENCES: " + "; ".join(problems)))
    for n in notes:
        print("note:", n)
    if out:
        write_output(Path(out), built, Path(path), plain=True)
    return not problems


def cube_part(material, size=500.0):
    """A cube with per-face UVs (0..1) and flat normals, counter-clockwise outside."""
    pos, nrm, uv, tris = [], [], [], []
    for axis in range(3):
        for sign in (1.0, -1.0):
            n = np.zeros(3)
            n[axis] = sign
            u = np.zeros(3)
            u[(axis + 1) % 3] = 1.0
            v = np.cross(n, u)
            base = len(pos)
            for du, dv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                pos.append((n + du * u + dv * v) * size / 2)
                nrm.append(n)
                uv.append(((du + 1) / 2, (1 - dv) / 2))
            tris += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    return Part(material, np.array(pos), np.array(nrm), np.array(uv), np.array(tris))


def cmd_selftest(template_path):
    data, *_ = load_model_bytes(template_path)
    t = Model(data)
    cube = cube_part(0)
    built = build_model(data, [cube], name="planet")
    m, notes, prims = validate(built)
    parts = extract_parts(m)
    p0 = [p for p in parts if p.material == 0][0]
    check(len(p0.triangles) == 12, f"cube has {len(p0.triangles)} triangles")
    if p0.uvs is None:  # the template's shape for this material sends no TEX0
        cube.uvs = None
    check(tri_signature(p0, colors=False) == tri_signature(cube), "cube triangles changed in the round trip")
    want = np.round(t.arrays[CLR0][[v[CLR0] for tri in t.shape_triangles([s for s, mm in t.shape_material.items() if mm == 0][0])
                                    for v in tri]].mean(0)) if CLR0 in t.arrays else np.full(4, 255)
    check(p0.colors is None or np.all(p0.colors == want), "missing colors must default to the template's mean color")
    # outward winding survives: GX clockwise in the file, counter-clockwise when extracted
    a, b, c = (p0.positions[p0.triangles[:, k]] for k in range(3))
    centroid = (a + b + c) / 3
    check(np.all((np.cross(b - a, c - a) * centroid).sum(1) > 0), "cube faces point inwards")
    check(p0.normals is None or np.allclose(p0.normals, np.round(p0.normals)), "cube normals changed")
    for blk in ("MAT3", "MDL3", "TEX1"):
        if blk in t.blocks:
            check(m.blocks.get(blk) == t.blocks[blk], f"{blk} changed")
    check(m.joint_names == ["planet"] and len(m.joints) == 1, "joint table")
    check(abs(m.joints[0]["radius"] - math.sqrt(3) * 250) < 1e-2, "joint radius")
    big = Part(0, np.random.default_rng(1).normal(size=(70000, 3)), None, None, np.zeros((0, 3), int))
    try:
        build_model(data, [big])
        raise AssertionError("70000 unique positions were accepted")
    except J3DError:
        pass
    bmd = build_model(data, [cube], fmt="bmd")
    mb, _, _ = validate(bmd)
    check(mb.kind == "bmd3" and "MDL3" not in mb.blocks, "bmd output")
    print(f"selftest ok: cube with {t.mat_names[0]!r} -> {len(built)} bytes ({m.kind}, {prims} draw commands, "
          f"{t.mat_num - 1} other material(s) given a degenerate shape)")
    for n in notes:
        print("note:", n)


def write_output(out: Path, model: bytes, template_path: Path, plain: bool):
    if out.suffix.lower() == ".arc":
        _, arc, idx, fname = load_model_bytes(template_path)
        check(arc is not None, ".arc output needs an .arc template")
        arc.contents[idx] = model
        raw = arc.build()
        if not plain:
            from stage_edit import yaz0_compress
            raw = yaz0_compress(raw)
        out.write_bytes(raw)
        print(f"wrote {out} ({len(raw)} bytes): {fname} replaced in a copy of {template_path.name}")
    else:
        out.write_bytes(model)
        print(f"wrote {out} ({len(model)} bytes)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info")
    p.add_argument("model")
    p = sub.add_parser("check")
    p.add_argument("model")
    p = sub.add_parser("roundtrip")
    p.add_argument("model")
    p.add_argument("--out")
    p = sub.add_parser("selftest")
    p.add_argument("template", nargs="?")
    p = sub.add_parser("from-obj")
    p.add_argument("template")
    p.add_argument("obj")
    p.add_argument("out")
    p.add_argument("--materials", default="", help="OBJ material name=template material index, comma separated "
                                                    "(* = default for unmapped groups)")
    p.add_argument("--scale", type=float, default=1.0, help="multiply OBJ coordinates (game units: Mario is about 160 tall)")
    p.add_argument("--name", help="root joint name (default: the template's)")
    p.add_argument("--format", choices=("bdl", "bmd"), help="output type (default: the template's)")
    p.add_argument("--no-flip-v", action="store_true", help="keep OBJ v as GX t (default: t = 1 - v)")
    p.add_argument("--plain", action="store_true", help=".arc output without Yaz0 compression")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "info":
            cmd_info(a.model)
        elif a.cmd == "check":
            cmd_check(a.model)
        elif a.cmd == "roundtrip":
            return 0 if cmd_roundtrip(a.model, a.out) else 1
        elif a.cmd == "selftest":
            tp = a.template
            if tp is None:
                tp = Path.home() / "Library/Application Support/Petari/Disc/RMGE01/files/ObjectData/StardustHillPlanet.arc"
            cmd_selftest(tp)
        elif a.cmd == "from-obj":
            data, *_ = load_model_bytes(a.template)
            t = Model(data)
            mapping = {}
            for item in filter(None, a.materials.split(",")):
                k, _, v = item.partition("=")
                v = v.strip()
                check(v.isdigit() or v in t.mat_names, f"--materials {item}: no template material {v!r} ({', '.join(t.mat_names)})")
                mapping[k.strip()] = int(v) if v.isdigit() else t.mat_names.index(v)
            parts = read_obj(Path(a.obj), mapping, a.scale, not a.no_flip_v, t)
            model = build_model(data, parts, a.name, a.format)
            _, notes, _ = validate(model)
            for n in notes:
                print("note:", n)
            write_output(Path(a.out), model, Path(a.template), a.plain)
    except J3DError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

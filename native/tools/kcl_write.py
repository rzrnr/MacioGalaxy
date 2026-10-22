#!/usr/bin/env python3
"""Build Super Mario Galaxy collision (.kcl) and its attribute table (.pa) from a triangle mesh.

The layout is the one KCollisionServer (src/Game/Map/KCollision*.cpp) reads and that
PetariNative::KCL::convertInPlace (native/resource/kcl_collision.cpp) validates when an
archive is mounted. Files are written big-endian, exactly as on the disc; the native port
converts them to host order itself.

  kcl_write.py selftest [--disc FILES] [--quick]
      Builds synthetic meshes and checks them with a Python port of the game's queries
      (searchBlock, checkPoint, checkSphere/KCHitSphere, checkArrow/KCHitArrow); with the
      disc, also rebuilds planet .kcl files from their own triangles and compares queries.
  kcl_write.py from-obj OBJ OUT.kcl OUT.pa [--scale S] [--z-up] [--floor Normal]
      [--wall Normal] [--sound Stone] [--camera-through 0] [--codes MAP.json]
      Wavefront OBJ -> .kcl + .pa. Every triangle gets the default attribute row unless its
      `usemtl` name carries codes ("Floor=Ice_Sound=Snow", tokens split at _ , ; . space;
      keys Floor, Wall, Sound, Camera (through), CameraId) or MAP.json maps the material
      name to {"Floor_code": "Ice", "Sound_code": "Snow", ...}.
  kcl_write.py info FILE.kcl [FILE.pa]
      Print a .kcl header / octree statistics and a .pa's columns.

KCL layout (all big-endian):
  0x00 u32 position offset   0x04 u32 normal offset   0x08 u32 prism offset (prism 0, unused,
  overlaps the last 16 bytes of the normals)  0x0C u32 octree offset  0x10 f32 prism thickness
  (40.0 on every disc planet)  0x14 f32 min[3]  0x20 s32 x/y/z masks (~(width-1), widths are
  powers of two)  0x2C s32 block width shift (root cell = 1 << shift)  0x30 s32 x shift
  (log2 x root cells)  0x34 s32 xy shift (log2 x cells + log2 y cells). Header is 0x38 bytes;
  SMG has no extra header field.
  Prism (16 bytes): f32 height, u16 position (vertex 0), u16 face normal, u16 edge normal[3],
  u16 attribute (row of the .pa). Edge normals: [0] edge v0-v2, [1] edge v0-v1, [2] edge v1-v2
  (opposite v0); height = distance from v0 to edge v1-v2.
  Octree: root cells (z << xyShift | y << xShift | x) of s32 words; a word with the high bit set
  is a leaf whose low 31 bits point (relative to the current block) at the u16 before a
  0-terminated list of 1-based prism indices; otherwise it is the offset (relative to the current
  block) of 8 child words indexed (z & 1) << 2 | (y & 1) << 1 | (x & 1).
"""
import argparse
import json
import math
import random
import struct
import sys
from pathlib import Path

import numpy as np

HEADER_SIZE = 0x38
PRISM_SIZE = 0x10
DISC_FILES = Path.home() / "Library/Application Support/Petari/Disc/RMGE01/files"

# --- attribute codes (src/Game/Map/CollisionCode.cpp; enum values are table order) ------------

FLOOR_CODES = ("Normal Death Slip NoSlip DamageNormal Ice JumpLow JumpMiddle JumpHigh Slider DamageFire JumpNormal "
               "FireDance Sand Glass DamageElectric PullBack Sink SinkPoison Slide WaterBottomH WaterBottomM "
               "WaterBottomL Wet Needle SinkDeath Snow RailMove AreaMove Press NoStampSand SinkDeathMud Brake "
               "GlassIce JumpParasol").split()
WALL_CODES = "Normal NotWallJump NotWallSlip NotGrab GhostThroughCode NotSideStep Rebound Fur NoAction".split()
SOUND_CODES = "null Soil Lawn Stone Marble WoodThick WoodThin Metal Snow Ice Shallow Sand Beach Carpet Mud Honey".split()
CAMERA_CODES = "NoThrough Through".split()

# Column layout of 249 of the 309 planet .pa files on the US disc: one u32 per row, bit fields.
# (name, mask, shift); every field has type 0 (int).
PA_FIELDS = (("camera_id", 0x000000FF, 0), ("Sound_code", 0x00007F00, 8), ("Floor_code", 0x001F8000, 15),
             ("Wall_code", 0x01E00000, 21), ("Camera_through", 0x02000000, 25))
PA_TABLES = {"Floor_code": FLOOR_CODES, "Wall_code": WALL_CODES, "Sound_code": SOUND_CODES, "Camera_through": CAMERA_CODES}
# Plain walkable ground: no camera (255), Stone footsteps, Normal floor and wall, camera blocked.
DEFAULT_ROW = {"camera_id": 255, "Sound_code": 3, "Floor_code": 0, "Wall_code": 0, "Camera_through": 0}


def jmap_hash(name: str) -> int:
    """JMapInfo field-name hash (as native/tools/stage_edit.py)."""
    value = 0
    for byte in name.encode("latin-1"):
        if byte >= 128:
            byte -= 256
        value = (byte + value * 31) & 0xFFFFFFFF
    return value


def code_value(column: str, value) -> int:
    """A .pa column value from a number or a code name (case-insensitive)."""
    if isinstance(value, (int, np.integer)):
        return int(value)
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    table = PA_TABLES.get(column)
    if table:
        for i, name in enumerate(table):
            if name.lower() == text.lower():
                return i
    raise ValueError(f"{column}: unknown code {value!r}" + (f" (one of {', '.join(table)})" if table else ""))


def normalize_row(row) -> dict:
    out = dict(DEFAULT_ROW)
    for key, value in (row or {}).items():
        column = {"floor": "Floor_code", "wall": "Wall_code", "sound": "Sound_code", "camera": "Camera_through",
                  "camerathrough": "Camera_through", "cameraid": "camera_id"}.get(key.lower().replace("_", ""), key)
        if column not in out:
            raise ValueError(f"unknown .pa column {key!r}")
        out[column] = code_value(column, value)
    for name, mask, shift in PA_FIELDS:
        if not 0 <= out[name] <= mask >> shift:
            raise ValueError(f"{name}={out[name]} does not fit the column")
    return out


# --- .pa (BCSV) -------------------------------------------------------------------------------


def build_pa(rows) -> bytes:
    """BCSV table with the disc's .pa field hashes, masks and types; rows are dicts of codes."""
    rows = [normalize_row(r) for r in rows]
    out = bytearray(struct.pack(">4I", len(rows), len(PA_FIELDS), 16 + 12 * len(PA_FIELDS), 4))
    for name, mask, shift in PA_FIELDS:
        out += struct.pack(">IIHBB", jmap_hash(name), mask, 0, shift, 0)
    for row in rows:
        word = 0
        for name, mask, shift in PA_FIELDS:
            word |= (row[name] << shift) & mask
        out += struct.pack(">I", word)
    out += b"@" * (-len(out) % 32)
    return bytes(out)


def read_pa(data: bytes):
    """(columns, rows): columns are (name or hash, mask, offset, shift, type); rows are dicts."""
    count, nfields, data_offset, entry_size = struct.unpack_from(">4I", data, 0)
    known = {jmap_hash(n): n for n in ("camera_id", "Sound_code", "Floor_code", "Wall_code", "Camera_through",
                                       "Cave_code", "Camera_type")}
    columns = []
    for i in range(nfields):
        h, mask, offset, shift, kind = struct.unpack_from(">IIHBB", data, 16 + 12 * i)
        columns.append((known.get(h, f"0x{h:08x}"), mask, offset, shift, kind))
    rows = []
    for r in range(count):
        base = data_offset + r * entry_size
        row = {}
        for name, mask, offset, shift, kind in columns:
            if kind in (0, 3):
                row[name] = (struct.unpack_from(">I", data, base + offset)[0] & mask) >> shift
            elif kind == 4:
                row[name] = (struct.unpack_from(">H", data, base + offset)[0] & mask) >> shift
            elif kind == 5:
                row[name] = (data[base + offset] & mask) >> shift
            elif kind == 2:
                row[name] = struct.unpack_from(">f", data, base + offset)[0]
            else:
                row[name] = None
        rows.append(row)
    return columns, rows


# --- geometry ---------------------------------------------------------------------------------


def _unit(v):
    length = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.where(length == 0, 1, length)


def prism_geometry(v0, v1, v2):
    """Face normal, edge normals [v0-v2, v0-v1, v1-v2] and height, as KCollisionServer expects."""
    n = _unit(np.cross(v1 - v0, v2 - v0))
    e0 = _unit(np.cross(n, v2 - v0))
    e1 = _unit(np.cross(v1 - v0, n))
    e2 = _unit(np.cross(v2 - v1, n))
    height = np.einsum("ij,ij->i", v1 - v0, e2)
    return n, e0, e1, e2, height


def _sat_overlap(points, axes, lo, hi):
    """Per row: does the convex hull of points (T,P,3) overlap the box [lo,hi]? axes (T,K,3)."""
    center = (lo + hi) * 0.5
    half = (hi - lo) * 0.5
    proj = np.einsum("tpc,tkc->tkp", points, axes)
    pmin, pmax = proj.min(axis=2), proj.max(axis=2)
    c = np.einsum("tkc,c->tk", axes, center)
    r = np.einsum("tkc,c->tk", np.abs(axes), half)
    return np.all((pmin <= c + r) & (pmax >= c - r), axis=1)


class _PrismVolumes:
    """Triangles extruded backwards by the prism thickness; box overlap by separating axes."""

    def __init__(self, v0, v1, v2, n, e0, e1, e2, thickness):
        back = -n * thickness
        self.points = np.stack([v0, v1, v2, v0 + back, v1 + back, v2 + back], axis=1)
        box = np.broadcast_to(np.eye(3), (len(v0), 3, 3))
        edges = [v1 - v0, v2 - v1, v0 - v2, n]
        crosses = [np.cross(np.eye(3)[None, i], edge) for i in range(3) for edge in edges]
        self.axes = np.concatenate([box, np.stack([n, e0, e1, e2], axis=1), np.stack(crosses, axis=1)], axis=1)
        self.lo = self.points.min(axis=1)
        self.hi = self.points.max(axis=1)

    def overlap(self, idx, lo, hi):
        idx = idx[np.all((self.lo[idx] <= hi) & (self.hi[idx] >= lo), axis=1)]
        if len(idx) == 0:
            return idx
        return idx[_sat_overlap(self.points[idx], self.axes[idx], lo, hi)]


# --- .kcl writer ------------------------------------------------------------------------------


def _pow2_at_least(value: int) -> int:
    width = 1
    while width < value:
        width <<= 1
    return width


def build_kcl(positions, triangles, attributes=None, thickness=40.0, max_triangles=32, min_cell=None,
              margin=1.0, report=None):
    """KCL bytes for a mesh.

    positions (N,3) floats in game units; triangles (M,3) vertex indices, counter-clockwise seen
    from the walkable side; attributes: per-triangle .pa row index (default 0). Degenerate
    triangles are skipped (report["kept"] maps prism i+1 -> input triangle). The octree keeps
    splitting cells that list more than max_triangles prisms down to min_cell (power of two).
    A prism is listed in every cell its volume (triangle plus `thickness` behind it) touches,
    with cells grown by `margin` units.
    """
    report = report if report is not None else {}
    positions = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
    triangles = np.asarray(triangles, dtype=np.int64).reshape(-1, 3)
    if attributes is None:
        attributes = np.zeros(len(triangles), dtype=np.int64)
    attributes = np.asarray(attributes, dtype=np.int64).reshape(-1)
    if len(attributes) != len(triangles):
        raise ValueError("one attribute per triangle")
    if len(triangles) and (triangles.min() < 0 or triangles.max() >= len(positions)):
        raise ValueError("triangle index outside the positions")
    if len(attributes) and (attributes.min() < 0 or attributes.max() > 0xFFFF):
        raise ValueError("attribute index outside u16")

    # Geometry from the float32 positions the game will see.
    pos32 = positions.astype(np.float32).astype(np.float64)
    v0, v1, v2 = (pos32[triangles[:, k]] for k in range(3))
    area2 = np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
    n, e0, e1, e2, height = prism_geometry(v0, v1, v2)
    longest = np.max([np.linalg.norm(v1 - v0, axis=1), np.linalg.norm(v2 - v1, axis=1),
                      np.linalg.norm(v0 - v2, axis=1)], axis=0) if len(triangles) else np.zeros(0)
    keep = (area2 > 1e-6) & (height > 1e-4 * np.maximum(longest, 1e-9)) & np.isfinite(height)
    kept = np.nonzero(keep)[0]
    report["kept"] = kept
    report["skipped"] = int(len(triangles) - len(kept))
    if len(kept) == 0:
        raise ValueError("no usable triangles")
    if len(kept) > 0xFFFF:
        raise ValueError(f"{len(kept)} triangles: a KCL holds at most 65535")
    v0, v1, v2, n, e0, e1, e2, height = (a[kept] for a in (v0, v1, v2, n, e0, e1, e2, height))
    attributes = attributes[kept]

    # Deduplicated float32 positions (vertex 0 of each prism) and normals.
    def dedup(vectors):
        f32 = np.ascontiguousarray(vectors.astype(">f4"))
        table, index = {}, np.empty(len(f32), dtype=np.int64)
        for i, key in enumerate(map(bytes, f32)):
            index[i] = table.setdefault(key, len(table))
        return b"".join(table), index, len(table)

    pos_bytes, pos_index, npos = dedup(v0)
    nrm_bytes, nrm_index, nnrm = dedup(np.concatenate([n, e0, e1, e2]))
    if npos > 0xFFFF or nnrm > 0xFFFF:
        raise ValueError(f"{npos} positions / {nnrm} normals: indices are u16")
    count = len(v0)
    nrm_index = nrm_index.reshape(4, count)

    # Bounds of the prism volumes (as on the disc: a floor's prism reaches `thickness` below
    # it, so points just under the lowest floor still find it); power-of-two widths.
    back = -n * thickness
    corners = np.concatenate([v0, v1, v2, v0 + back, v1 + back, v2 + back])
    vmin, vmax = corners.min(0), corners.max(0)
    origin = vmin.astype(np.float32).astype(np.float64)
    widths = [_pow2_at_least(int(math.floor(vmax[a] - origin[a])) + 2) for a in range(3)]
    if min_cell is None:
        min_cell = 8
    min_cell = _pow2_at_least(int(min_cell))
    widths = [max(w, min_cell) for w in widths]
    block = max(min(widths) >> 1, min_cell)
    while (widths[0] // block) * (widths[1] // block) * (widths[2] // block) > 1024:
        block <<= 1
    widths = [max(w, block) for w in widths]
    shift = block.bit_length() - 1
    cells = [w // block for w in widths]
    x_shift = cells[0].bit_length() - 1
    xy_shift = x_shift + cells[1].bit_length() - 1

    # Octree: cells in game-local coordinates (relative to origin).
    volumes = _PrismVolumes(v0 - origin, v1 - origin, v2 - origin, n, e0, e1, e2, thickness)
    everything = np.arange(count)

    def make(lo, size, candidates):
        hits = volumes.overlap(candidates, lo - margin, lo + size + margin)
        if len(hits) <= max_triangles or size <= min_cell:
            return ("leaf", tuple(int(i) + 1 for i in hits))
        half = size // 2
        children = []
        for c in range(8):
            off = np.array([(c & 1) * half, ((c >> 1) & 1) * half, ((c >> 2) & 1) * half], dtype=np.float64)
            children.append(make(lo + off, half, hits))
        return ("node", children)

    roots = []
    for z in range(cells[2]):
        for y in range(cells[1]):
            for x in range(cells[0]):
                roots.append(make(np.array([x, y, z], dtype=np.float64) * block, block, everything))

    # Layout: root words, then 8-word child blocks breadth first, then shared prism lists.
    blocks = [roots]  # breadth-first; a branch's children form the next unclaimed block
    for nodes in blocks:
        blocks.extend(node[1] for node in nodes if node[0] == "node")
    starts, cursor = [], 0
    for nodes in blocks:
        starts.append(cursor)
        cursor += len(nodes)
    octree_words = cursor
    list_base = octree_words * 4
    # Identical lists are shared. The empty list (a lone 0) comes first, so its "u16 before"
    # is the low half of the last octree word, which searchBlock's caller skips.
    lists = {}
    for nodes in blocks:
        for node in nodes:
            if node[0] == "leaf":
                lists.setdefault(node[1], None)
    list_order = sorted(lists, key=len)
    list_data = bytearray()
    for entries in list_order:
        lists[entries] = list_base + len(list_data) - 2  # offset of the u16 before the entries
        list_data += struct.pack(f">{len(entries) + 1}H", *entries, 0)
    child_of = {}
    next_block = 1
    for b, nodes in enumerate(blocks):
        for i, node in enumerate(nodes):
            if node[0] == "node":
                child_of[(b, i)] = next_block
                next_block += 1
    octree = bytearray()
    for b, nodes in enumerate(blocks):
        base = starts[b] * 4
        for i, node in enumerate(nodes):
            if node[0] == "leaf":
                value = 0x80000000 | (lists[node[1]] - base)
            else:
                value = starts[child_of[(b, i)]] * 4 - base
            octree += struct.pack(">I", value)
    octree += list_data

    # Sections.
    pos_offset = HEADER_SIZE
    nrm_offset = pos_offset + len(pos_bytes)
    prism_offset = nrm_offset + len(nrm_bytes) - PRISM_SIZE
    octree_offset = prism_offset + PRISM_SIZE * (count + 1)
    prisms = bytearray()
    h32 = height.astype(np.float32)
    for i in range(count):
        prisms += struct.pack(">f6H", float(h32[i]), int(pos_index[i]), int(nrm_index[0, i]), int(nrm_index[1, i]),
                              int(nrm_index[2, i]), int(nrm_index[3, i]), int(attributes[i]))
    header = struct.pack(">4If3f3i3i", pos_offset, nrm_offset, prism_offset, octree_offset, float(thickness),
                         *map(float, origin), *[~(w - 1) for w in widths], shift, x_shift, xy_shift)
    data = header + pos_bytes + nrm_bytes + bytes(prisms) + bytes(octree)
    report.update(widths=widths, block=block, root_cells=cells, positions=npos, normals=nnrm, prisms=count,
                  octree_words=octree_words, lists=len(list_order),
                  max_list=max((len(e) for e in list_order), default=0), size=len(data))
    error = validate_kcl(data)
    if error:
        raise AssertionError(f"generated KCL fails the native checks: {error}")
    return data


# --- native resource checks (port of PetariNative::KCL::convertInPlace validation) ------------


def validate_kcl(data: bytes):
    """None if native/resource/kcl_collision.cpp would accept the resource, else its message."""
    size = len(data)
    if size < HEADER_SIZE:
        return "resource smaller than the KCL header"
    pos, nrm, prism, octree = struct.unpack_from(">4I", data, 0)
    if pos & 0x80000000:
        return "resource is already initialized"
    if not (HEADER_SIZE <= pos <= nrm <= prism + PRISM_SIZE <= octree < size):
        return "section offsets out of order"
    if (nrm - pos) % 12 or (prism + PRISM_SIZE - nrm) % 12 or (octree - prism) % PRISM_SIZE:
        return "section sizes are not whole elements"
    npos, nnrm, nprism = (nrm - pos) // 12, (prism + PRISM_SIZE - nrm) // 12, (octree - prism) // PRISM_SIZE
    for i in range(1, nprism):
        fields = struct.unpack_from(">5H", data, prism + i * PRISM_SIZE + 4)
        if fields[0] >= npos:
            return "prism references a missing position"
        if any(f >= nnrm for f in fields[1:5]):
            return "prism references a missing normal"
    masks = struct.unpack_from(">3i", data, 0x20)
    width_shift, x_shift, xy_shift = struct.unpack_from(">3i", data, 0x2C)
    if not (0 <= width_shift <= 31 and -1 <= x_shift <= 31 and -1 <= xy_shift <= 31):
        return "octree shifts out of range"
    cells = 1
    if not (x_shift == -1 and xy_shift == -1):
        for m in masks:
            cells *= ((~m & 0xFFFFFFFF) >> width_shift) + 1
        if cells * 4 > size - octree:
            return "octree top level outside the resource"
    marks = bytearray(size)
    stack = [(octree, c * 4, 0) for c in range(cells)]
    while stack:
        base, word_offset, depth = stack.pop()
        word = base + word_offset
        if word < octree or word > size - 4:
            return "octree word outside the resource"
        if marks[word] == 1:
            continue
        if marks[word] or depth > 32:
            return "octree words overlap other data"
        marks[word] = 1
        value = struct.unpack_from(">I", data, word)[0]
        if value & 0x80000000:
            entry = base + (value & 0x7FFFFFFF) + 2
            while True:
                if entry < octree or entry > size - 2:
                    return "prism list outside the resource"
                if marks[entry] == 2:
                    break
                if marks[entry]:
                    return "prism list overlaps octree words"
                marks[entry] = 2
                index = struct.unpack_from(">H", data, entry)[0]
                if index == 0:
                    break
                if index >= nprism:
                    return "prism list references a missing prism"
                entry += 2
        else:
            child = base + value
            stack.extend((child, i * 4, depth + 1) for i in range(8))
    return None


# --- game queries (Python port of KCollisionServer) -------------------------------------------


def _s32(value: float) -> int:
    """C (s32) cast of a float stored into a u32."""
    return int(value) & 0xFFFFFFFF


def _signed(value: int) -> int:
    return value - (1 << 32) if value & 0x80000000 else value


class KclServer:
    """Reads a big-endian (disc-format) KCL and answers queries like KCollisionServer."""

    def __init__(self, data: bytes):
        self.data = data
        (self.pos_off, self.nrm_off, self.prism_off, self.octree_off, self.thickness, *rest) = struct.unpack_from(
            ">4If3f3i3i", data, 0)
        self.min = rest[0:3]
        self.masks = [m & 0xFFFFFFFF for m in rest[3:6]]
        self.width_shift, self.x_shift, self.xy_shift = rest[6:9]
        npos = (self.nrm_off - self.pos_off) // 12
        nnrm = (self.prism_off + PRISM_SIZE - self.nrm_off) // 12
        self.pos = [struct.unpack_from(">3f", data, self.pos_off + 12 * i) for i in range(npos)]
        self.nrm = [struct.unpack_from(">3f", data, self.nrm_off + 12 * i) for i in range(nnrm)]
        self.count = (self.octree_off - self.prism_off) // PRISM_SIZE - 1
        self.prisms = [None] + [struct.unpack_from(">f6H", data, self.prism_off + PRISM_SIZE * i)
                                for i in range(1, self.count + 1)]
        self._lists = {}

    # prism: (height, position, face normal, edge0, edge1, edge2, attribute)

    def get_pos(self, index, vertex):
        h, p, fn, a, b, c, _ = self.prisms[index]
        pos, n = self.pos[p], self.nrm[fn]
        if vertex == 0:
            return pos
        if vertex == 1:
            ea = self.nrm[b]
            cx = (n[1] * ea[2] - n[2] * ea[1], n[2] * ea[0] - n[0] * ea[2], n[0] * ea[1] - n[1] * ea[0])  # n x en1
        else:
            ea = self.nrm[a]
            cx = (ea[1] * n[2] - ea[2] * n[1], ea[2] * n[0] - ea[0] * n[2], ea[0] * n[1] - ea[1] * n[0])  # en0 x n
        e2 = self.nrm[c]
        denominator = cx[0] * e2[0] + cx[1] * e2[1] + cx[2] * e2[2]
        if denominator == 0.0:  # degenerate prism (the game gets inf/nan here)
            return (math.nan, math.nan, math.nan)
        side = h / denominator
        return (pos[0] + side * cx[0], pos[1] + side * cx[1], pos[2] + side * cx[2])

    def triangles(self):
        """(M,3,3) vertices of prisms 1..M, reconstructed as KCollisionServer::getPos does."""
        return np.array([[self.get_pos(i, k) for k in range(3)] for i in range(1, self.count + 1)])

    def search_block(self, x, y, z):
        """(byte offset of the u16 before the prism list, shift) for local coordinates."""
        shift = self.width_shift
        if self.xy_shift == -1 and self.x_shift == -1:
            offset = 0
        else:
            offset = (((z >> shift) << self.xy_shift) | ((y >> shift) << self.x_shift) | (x >> shift)) * 4
        base = self.octree_off
        while True:
            value = _signed(struct.unpack_from(">I", self.data, base + offset)[0])
            if value < 0:
                return base + (value & 0x7FFFFFFF), shift
            base += value
            shift -= 1
            offset = ((((z >> shift) & 1) << 2) | (((y >> shift) & 1) << 1) | ((x >> shift) & 1)) * 4

    def prism_list(self, at):
        cached = self._lists.get(at)
        if cached is None:
            entries, entry = [], at + 2
            while True:
                index = struct.unpack_from(">H", self.data, entry)[0]
                if index == 0:
                    break
                entries.append(index)
                entry += 2
            cached = self._lists[at] = tuple(entries)
        return cached

    def _local(self, p):
        return tuple(_s32(p[k] - self.min[k]) for k in range(3))

    def check_point(self, p, param=1.0):
        """(prism, distance below the face) or None (KCollisionServer::checkPoint)."""
        max_dist = self.thickness * param
        x, y, z = self._local(p)
        if x & self.masks[0] or y & self.masks[1] or z & self.masks[2]:
            return None
        at, _ = self.search_block(x, y, z)
        for index in self.prism_list(at):
            h, pi, fn, a, b, c, _ = self.prisms[index]
            if h <= 0.0:
                continue
            v = self.pos[pi]
            d = (p[0] - v[0], p[1] - v[1], p[2] - v[2])
            if _dot(d, self.nrm[a]) > 0.0 or _dot(d, self.nrm[b]) > 0.0 or _dot(d, self.nrm[c]) > h:
                continue
            dist = -_dot(d, self.nrm[fn])
            if dist < 0.0 or max_dist < dist:
                continue
            return index, dist
        return None

    def _out_check(self, lo, hi):
        a = [_signed(v) for v in self._local(lo)]
        b = [_signed(v) for v in self._local(hi)]
        a = [max(v, 0) for v in a]
        b = [min(v, _signed(~m & 0xFFFFFFFF)) for v, m in zip(b, self.masks)]
        if any(bv < av for av, bv in zip(a, b)):
            return None
        return a, b

    def _walk_cells(self, lo, hi):
        """Prism lists in the order checkSphere/checkArea3D visit them (with their skip rule)."""
        box = self._out_check(lo, hi)
        if box is None:
            return
        (x0, y0, z0), (x1, y1, z1) = box
        skip = next_skip = None
        z = z0
        while True:
            y, z_step = y0, 1000000
            while True:
                x, y_step, best_rem_y = x0, 1000000, 0
                while True:
                    at, shift = self.search_block(x, y, z)
                    size = 1 << shift
                    mask = size - 1
                    rem_x, rem_y, rem_z = size - (x & mask), size - (y & mask), size - (z & mask)
                    z_step = min(z_step, rem_z)
                    y_step = min(y_step, rem_y)
                    entries = self.prism_list(at)
                    if rem_y > best_rem_y and entries:
                        best_rem_y, next_skip = rem_y, at
                    if skip is None or at != skip:
                        yield entries
                    x += rem_x
                    if x > x1:
                        break
                skip = next_skip
                y += y_step
                if y > y1:
                    break
            z += z_step
            if z > z1:
                break

    def check_sphere(self, center, radius, param=1.0, max_count=64):
        """[(prism, depth, flag)] like KCollisionServer::checkSphere."""
        lo = [c - radius for c in center]
        hi = [c + radius for c in center]
        found, seen = [], set()
        for entries in self._walk_cells(lo, hi):
            for index in entries:
                if self.prisms[index][0] <= 0.0 or index in seen:
                    continue
                hit = self.hit_sphere(index, center, radius, param)
                if hit is None or len(found) >= max_count:
                    continue
                seen.add(index)
                found.append((index, hit[0], hit[1]))
        return found

    def hit_sphere(self, index, center, radius, param=1.0):
        """(depth, flag) or None: KCollisionServer::KCHitSphere."""
        h, pi, fn, a, b, c, _ = self.prisms[index]
        threshold = self.thickness * param
        v = self.pos[pi]
        d = (center[0] - v[0], center[1] - v[1], center[2] - v[2])
        n0, n1, n2 = self.nrm[a], self.nrm[b], self.nrm[c]
        d1 = _dot(d, n0)
        if d1 >= radius:
            return None
        d2 = _dot(d, n1)
        if d2 >= radius:
            return None
        d3 = _dot(d, n2) - h
        if d3 >= radius:
            return None
        d0 = _dot(d, self.nrm[fn])
        dist = radius - d0
        if dist < 0.0:
            return None
        if d1 > d2:
            side = 0 if d1 > d3 else 2
        else:
            side = 1 if d2 > d3 else 2
        region = None
        if side == 0:
            if d1 <= 0.0:
                return (dist, 1) if threshold >= dist else None
            if d2 > d3:
                nn = _dot(n0, n1)
                region = "v2" if nn * d1 > d2 else 5
            else:
                nn = _dot(n0, n2)
                region = "v2" if nn * d1 > d3 else 7
        elif side == 1:
            if d2 <= 0.0:
                return (dist, 1) if threshold >= dist else None
            if d3 > d1:
                nn = _dot(n1, n2)
                region = "v3" if nn * d2 > d3 else 6
            else:
                nn = _dot(n1, n0)
                region = "v3" if nn * d2 > d1 else 5
        else:
            if d3 <= 0.0:
                return (dist, 1) if threshold >= dist else None
            if d1 > d2:
                nn = _dot(n2, n0)
                region = "v4" if nn * d3 > d1 else 7
            else:
                nn = _dot(n2, n1)
                region = "v4" if nn * d3 > d2 else 6
        rsq = radius * radius
        if region in ("v2", "v3", "v4"):
            dv = {"v2": d1, "v3": d2, "v4": d3}[region]
            if dv > d0:
                return None
            dist, flag = rsq - dv * dv, {"v2": 2, "v3": 3, "v4": 4}[region]
        else:
            if region == 5:
                t = (nn * d2 - d1) / (nn * nn - 1.0)
                s = d2 - t * nn
                va, vb = n0, n1
            elif region == 6:
                t = (nn * d3 - d2) / (nn * nn - 1.0)
                s = d3 - t * nn
                va, vb = n1, n2
            else:
                t = (nn * d1 - d3) / (nn * nn - 1.0)
                s = d1 - t * nn
                va, vb = n2, n0
            w = (t * va[0] + s * vb[0], t * va[1] + s * vb[1], t * va[2] + s * vb[2])
            closest = _dot(w, w)
            length = math.sqrt(closest)
            if length > d0 or length >= radius:
                return None
            dist, flag = rsq - closest, region
        dist = math.sqrt(max(dist, 0.0)) - d0
        if dist < 0.0 or threshold < dist:
            return None
        return dist, flag

    def hit_arrow(self, index, origin, direction):
        """(t, flag) or None: KCollisionServer::KCHitArrow (t is a fraction of direction)."""
        h, pi, fn, a, b, c, _ = self.prisms[index]
        v, n = self.pos[pi], self.nrm[fn]
        rel = (origin[0] - v[0], origin[1] - v[1], origin[2] - v[2])
        t = _dot(rel, n)
        if t <= 0.0:
            return None
        dn = _dot(n, direction)
        if 0.0 < t + dn:
            return None
        t = t / -dn
        hit = (direction[0] * t + rel[0], direction[1] * t + rel[1], direction[2] * t + rel[2])
        if 0.01 < _dot(hit, self.nrm[a]) or 0.01 < _dot(hit, self.nrm[b]) or 0.01 + h < _dot(hit, self.nrm[c]):
            return None
        return t, 1

    def check_arrow(self, origin, direction, collect=False, max_count=64):
        """Nearest (prism, t) along origin + t*direction, t in [0,1] (KCollisionServer::checkArrow);
        with collect, every (prism, t) the traversal sees before stopping."""
        if direction == (0.0, 0.0, 0.0):
            return [] if collect else None
        length = math.sqrt(_dot(direction, direction))
        if length < 1e-6:
            return [] if collect else None
        d = tuple(v / length for v in direction)
        start = tuple(origin[k] - self.min[k] for k in range(3))
        start_t = 0.0

        def inside(p):
            cell = tuple(_s32(v) for v in p)
            return cell if all((cv & m) == 0 for cv, m in zip(cell, self.masks)) else None

        cell = inside(start)
        hit_point = list(start)
        if cell is None:
            box_max = [float(~m & 0xFFFFFFFF) for m in self.masks]
            for k in range(3):
                if d[k] != 0.0:
                    edge = 0.0 if d[k] > 0.0 else box_max[k]
                    start_t = (edge - start[k]) / d[k]
                    if 0.0 <= start_t <= length:
                        hit_point = [start[j] + d[j] * start_t for j in range(3)]
                        cell = inside(hit_point)
                        if cell is not None:
                            break
            if cell is None:
                return [] if collect else None
        steps = [-1 if d[k] < 0.0 else 1 for k in range(3)]
        best, best_t, found = None, None, []
        accum = start_t
        while True:
            at, shift = self.search_block(*cell)
            size = 1 << shift
            mask = size - 1
            deltas = []
            for k in range(3):
                delta = (size - (cell[k] & mask)) if steps[k] > 0 else -(cell[k] & mask)
                deltas.append(delta if delta != 0 else steps[k])
            best_fraction = 1.0
            for index in self.prism_list(at):
                if self.prisms[index][0] <= 0.0:
                    continue
                hit = self.hit_arrow(index, origin, direction)
                if hit is None:
                    continue
                if collect:
                    found.append((index, hit[0]))
                    if hit[0] < best_fraction:
                        best_fraction, best = hit[0], index
                    if len(found) == max_count:
                        return found
                elif hit[0] < best_fraction:
                    best_fraction, best, best_t = hit[0], index, hit[0]
            if not collect and best is not None:
                break
            ts = [1.0e9 if abs(d[k]) < 0.001 else deltas[k] / d[k] for k in range(3)]
            t_min = min(ts)
            if length - accum <= t_min:
                break
            hit_point = [hit_point[k] + d[k] * t_min for k in range(3)]
            accum += t_min
            cell = inside(hit_point)
            if cell is None or not accum < length:
                break
        if collect:
            return found
        return (best, best_t) if best is not None else None

    def leaves(self):
        """Every leaf: (local min corner, size, prism list)."""
        single = self.x_shift == -1 and self.xy_shift == -1
        widths = [(~m & 0xFFFFFFFF) + 1 for m in self.masks]
        block = 1 << self.width_shift
        counts = [1, 1, 1] if single else [max(w // block, 1) for w in widths]
        out = []

        def visit(base, offset, corner, size):
            value = _signed(struct.unpack_from(">I", self.data, base + offset)[0])
            if value < 0:
                out.append((corner, size, self.prism_list(base + (value & 0x7FFFFFFF))))
                return
            child = base + value
            half = size // 2
            for c in range(8):
                visit(child, c * 4, (corner[0] + (c & 1) * half, corner[1] + ((c >> 1) & 1) * half,
                                     corner[2] + ((c >> 2) & 1) * half), half)

        for z in range(counts[2]):
            for y in range(counts[1]):
                for x in range(counts[0]):
                    offset = 0 if single else ((z << self.xy_shift) | (y << self.x_shift) | x) * 4
                    visit(self.octree_off, offset, (x * block, y * block, z * block), block)
        return out


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


# --- OBJ --------------------------------------------------------------------------------------


def parse_material_codes(name: str):
    """Codes carried by a material name ("Floor=Ice_Sound=Snow"), or {} when it has none."""
    row = {}
    for token in name.replace(",", "_").replace(";", "_").replace(" ", "_").split("_"):
        token = token.split(".")[0] if "." in token and token.split(".")[-1].isdigit() else token
        for sep in ("=", ":", "-"):
            if sep in token:
                key, value = token.split(sep, 1)
                key = key.strip().lower()
                if key in ("floor", "wall", "sound", "camera", "camerathrough", "cameraid"):
                    column = {"floor": "Floor_code", "wall": "Wall_code", "sound": "Sound_code",
                              "camera": "Camera_through", "camerathrough": "Camera_through",
                              "cameraid": "camera_id"}[key]
                    row[column] = code_value(column, value)
                break
    return row


def read_obj(path):
    """(positions (N,3), triangles (M,3), material name per triangle); polygons are fanned."""
    positions, triangles, materials = [], [], []
    material = None
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "v":
                positions.append([float(v) for v in parts[1:4]])
            elif parts[0] == "usemtl":
                material = line.strip()[6:].strip()
            elif parts[0] == "f":
                idx = []
                for item in parts[1:]:
                    i = int(item.split("/")[0])
                    idx.append(i - 1 if i > 0 else len(positions) + i)
                for k in range(1, len(idx) - 1):
                    triangles.append((idx[0], idx[k], idx[k + 1]))
                    materials.append(material)
    return np.array(positions, dtype=np.float64).reshape(-1, 3), np.array(triangles, dtype=np.int64).reshape(-1, 3), materials


def cmd_from_obj(args):
    positions, triangles, materials = read_obj(args.obj)
    if args.z_up:
        positions = np.stack([positions[:, 0], positions[:, 2], -positions[:, 1]], axis=1)
    positions = positions * args.scale
    default = {"Floor_code": args.floor, "Wall_code": args.wall, "Sound_code": args.sound,
               "Camera_through": args.camera_through, "camera_id": args.camera_id}
    mapping = json.loads(Path(args.codes).read_text()) if args.codes else {}
    rows, row_of, attributes = [], {}, []
    for material in materials:
        row = dict(default)
        if material is not None:
            row.update(mapping.get(material, {}) or parse_material_codes(material))
        key = tuple(sorted(normalize_row(row).items()))
        if key not in row_of:
            row_of[key] = len(rows)
            rows.append(dict(key))
        attributes.append(row_of[key])
    report = {}
    kcl = build_kcl(positions, triangles, attributes, thickness=args.thickness, max_triangles=args.max_triangles,
                    min_cell=args.min_cell, report=report)
    Path(args.out_kcl).write_bytes(kcl)
    Path(args.out_pa).write_bytes(build_pa(rows))
    lo, hi = positions.min(0), positions.max(0)
    print(f"{len(triangles)} triangles ({report['skipped']} degenerate skipped), {len(rows)} attribute rows")
    print(f"bounds {np.round(lo, 1).tolist()} .. {np.round(hi, 1).tolist()} (game units)")
    print(f"widths {report['widths']}, root cell {report['block']}, {report['octree_words']} octree words, "
          f"{report['lists']} lists (longest {report['max_list']}), {report['size']} bytes")
    for i, row in enumerate(rows):
        print(f"  row {i}: " + ", ".join(f"{k}={_code_name(k, v)}" for k, v in row.items()))
    return 0


def _code_name(column, value):
    table = PA_TABLES.get(column)
    return table[value] if table and 0 <= value < len(table) else value


def cmd_info(args):
    data = Path(args.kcl).read_bytes()
    server = KclServer(data)
    widths = [(~m & 0xFFFFFFFF) + 1 for m in server.masks]
    leaves = server.leaves()
    sizes = sorted({s for _, s, _ in leaves})
    print(f"thickness {server.thickness}, min {server.min}, widths {widths}, block shift {server.width_shift}, "
          f"x shift {server.x_shift}, xy shift {server.xy_shift}")
    print(f"{len(server.pos)} positions, {len(server.nrm)} normals, {server.count} prisms, {len(leaves)} leaves "
          f"(sizes {sizes}), longest list {max(len(l) for _, _, l in leaves)}")
    print("native check:", validate_kcl(data) or "ok")
    if args.pa:
        columns, rows = read_pa(Path(args.pa).read_bytes())
        print("columns:", ", ".join(f"{c[0]} (mask 0x{c[1]:x}, shift {c[3]}, type {c[4]})" for c in columns))
        attrs = sorted({p[6] for p in server.prisms[1:]})
        print(f"{len(rows)} rows; prisms use rows {attrs[0]}..{attrs[-1]}")
    return 0


# --- self test --------------------------------------------------------------------------------


def _sphere_mesh(radius, subdivisions):
    t = (1 + 5 ** 0.5) / 2
    verts = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
             (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6),
             (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10),
             (8, 6, 7), (9, 8, 1)]
    verts = [np.array(v, dtype=np.float64) / np.linalg.norm(v) for v in verts]
    for _ in range(subdivisions):
        cache, new = {}, []

        def mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = verts[a] + verts[b]
                verts.append(m / np.linalg.norm(m))
                cache[key] = len(verts) - 1
            return cache[key]

        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            new += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = new
    return np.array(verts) * radius, np.array(faces)


def _grid_mesh(size, steps, height_fn):
    xs = np.linspace(-size / 2, size / 2, steps + 1)
    verts = np.array([(x, height_fn(x, z), z) for z in xs for x in xs])
    faces = []
    for j in range(steps):
        for i in range(steps):
            a, b, c, d = j * (steps + 1) + i, j * (steps + 1) + i + 1, (j + 1) * (steps + 1) + i, (j + 1) * (steps + 1) + i + 1
            faces += [(a, c, b), (b, c, d)]  # counter-clockwise seen from +y
    return verts, np.array(faces)


def verify_mesh(kcl: bytes, positions, triangles, kept, samples_per_triangle=2, rng=None, label=""):
    """Points just above / below each triangle must find it through the octree. Returns failures."""
    rng = rng or random.Random(1)
    server = KclServer(kcl)
    failures = checks = farther = 0
    tris = np.asarray(positions, dtype=np.float32).astype(np.float64)[np.asarray(triangles)[kept]]
    for p, tri in enumerate(tris, start=1):
        v0, v1, v2 = tri
        n = np.cross(v1 - v0, v2 - v0)
        n /= np.linalg.norm(n)
        for s in range(samples_per_triangle):
            a, b = rng.random(), rng.random()
            if a + b > 1:
                a, b = 1 - a, 1 - b
            if s == 0:
                a = b = 1 / 3
            else:  # pull towards the centroid: stay clear of the edges
                a, b = 1 / 3 + 0.9 * (a - 1 / 3), 1 / 3 + 0.9 * (b - 1 / 3)
            q = v0 + a * (v1 - v0) + b * (v2 - v0)
            above = tuple(q + n * 1.0)
            below = tuple(q - n * 1.0)
            checks += 1
            ok = True
            hits = server.check_sphere(above, 5.0, max_count=256)
            if p not in [h[0] for h in hits]:
                ok = False
            # checkPoint returns the first containing prism in list order: the triangle itself or
            # another prism containing the point at the same or a different depth.
            found = server.check_point(below)
            if found is None:
                ok = False
            arrow = server.check_arrow(tuple(q + n * 20.0), tuple(-n * 40.0), collect=True, max_count=256)
            if p not in [h[0] for h in arrow]:
                ok = False
            nearest = server.check_arrow(tuple(q + n * 20.0), tuple(-n * 40.0))
            if nearest is None:
                ok = False
            elif nearest[1] > 0.5 + 1e-3:
                # checkArrow stops in the first octree cell with any hit; overlapping geometry
                # listed there can win over a nearer prism (the disc files behave the same).
                farther += 1
            if not ok:
                failures += 1
    print(f"  {label}: {len(tris)} prisms, {checks} surface points: {failures} failures"
          + (f" ({farther} nearest-arrow answers from overlapping geometry)" if farther else ""))
    return failures


def _random_query_points(tris, normals, lo, hi, count, rng):
    points = []
    for i in range(count):
        if i % 2 == 0:
            points.append(tuple(lo[k] + (hi[k] - lo[k]) * rng.random() for k in range(3)))
        else:
            t = rng.randrange(len(tris))
            a, b = rng.random(), rng.random()
            if a + b > 1:
                a, b = 1 - a, 1 - b
            v0, v1, v2 = tris[t]
            q = v0 + a * (v1 - v0) + b * (v2 - v0) + normals[t] * rng.uniform(-50.0, 60.0)
            points.append(tuple(q))
    return points


def _sphere_hit_is_borderline(server, index, center, radius):
    """True when moving the centre by 0.05 units changes whether the prism is hit."""
    results = set()
    for dx, dy, dz in ((0, 0, 0), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
        p = (center[0] + 0.05 * dx, center[1] + 0.05 * dy, center[2] + 0.05 * dz)
        results.add(server.hit_sphere(index, p, radius) is not None)
    return len(results) > 1


def compare_servers(original: KclServer, rebuilt: KclServer, mapping, count, rng, label):
    """Same answers from both on random points (mapping: rebuilt prism -> original prism)."""
    tris = original.triangles()
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    widths = [(~m & 0xFFFFFFFF) + 1 for m in original.masks]
    lo = np.array(original.min) - 100
    hi = np.array(original.min) + np.array(widths) + 100
    stats = dict.fromkeys(("sphere_only_disc", "sphere_only_rebuilt", "sphere_borderline", "sphere_hits",
                           "point_none", "point_order", "point_hits", "arrow_none", "arrow_t", "arrow_hits"), 0)
    points = _random_query_points(tris, normals, lo, hi, count, rng)
    for i, p in enumerate(points):
        radius = rng.choice((10.0, 30.0, 70.0))
        a = {h[0] for h in original.check_sphere(p, radius, max_count=512)}
        b = {mapping[h[0]] for h in rebuilt.check_sphere(p, radius, max_count=512)}
        stats["sphere_hits"] += len(a)
        for k in a ^ b:
            if _sphere_hit_is_borderline(original, k, p, radius):
                stats["sphere_borderline"] += 1
            elif k in a:
                stats["sphere_only_disc"] += 1
            else:
                stats["sphere_only_rebuilt"] += 1
        pa, pb = original.check_point(p), rebuilt.check_point(p)
        stats["point_hits"] += pa is not None
        if (pa is None) != (pb is None):
            stats["point_none"] += 1
        elif pa and abs(pa[1] - pb[1]) > 0.05:
            stats["point_order"] += 1  # several prisms contain the point; list order picks one
        direction = tuple(-normals[i % len(normals)] * 300.0) if i % 2 else (0.0, -400.0, 0.0)
        aa, ab = original.check_arrow(p, direction), rebuilt.check_arrow(p, direction)
        stats["arrow_hits"] += aa is not None
        if (aa is None) != (ab is None):
            stats["arrow_none"] += 1
        elif aa and abs(aa[1] - ab[1]) * math.sqrt(_dot(direction, direction)) > 0.05:
            stats["arrow_t"] += 1
    print(f"  {label}: {count} random points"
          f"\n    checkSphere: {stats['sphere_hits']} disc hits; only disc {stats['sphere_only_disc']}, "
          f"only rebuilt {stats['sphere_only_rebuilt']}, borderline {stats['sphere_borderline']}"
          f"\n    checkPoint: {stats['point_hits']} disc hits; hit/miss differs {stats['point_none']}, "
          f"other containing prism {stats['point_order']}"
          f"\n    checkArrow: {stats['arrow_hits']} disc hits; hit/miss differs {stats['arrow_none']}, "
          f"distance differs {stats['arrow_t']}")
    return stats["sphere_only_disc"] + stats["point_none"] + stats["arrow_none"]


def disc_planets(files_dir, names):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from stage_edit import Archive  # noqa: E402
    out = []
    for name in names:
        path = Path(files_dir) / "ObjectData" / f"{name}.arc"
        if not path.exists():
            continue
        archive = Archive(path.read_bytes())
        kcl = pa = None
        for entry, index in archive.files.items():
            if entry.endswith(".kcl"):
                kcl = archive.contents[index]
            elif entry.endswith(".pa"):
                pa = archive.contents[index]
        if kcl:
            out.append((name, kcl, pa))
    return out


def cmd_selftest(args):
    rng = random.Random(7)
    failures = 0
    print("synthetic meshes:")
    meshes = [("icosphere r=1500 (planet)", *_sphere_mesh(1500.0, 3)),
              ("terrain 6000x6000", *_grid_mesh(6000.0, 24, lambda x, z: 300 * math.sin(x / 700) * math.cos(z / 900))),
              ("small sphere r=40", *_sphere_mesh(40.0, 1))]
    for label, verts, faces in meshes:
        report = {}
        attrs = np.arange(len(faces)) % 3
        kcl = build_kcl(verts, faces, attrs, report=report)
        assert validate_kcl(kcl) is None
        server = KclServer(kcl)
        assert server.count == len(report["kept"])
        assert all(server.prisms[i + 1][6] == attrs[report["kept"][i]] for i in range(server.count)), "attribute order"
        # Reconstructed vertices match the input (getPos).
        rebuilt = server.triangles()
        original = np.asarray(verts, dtype=np.float32)[np.asarray(faces)[report["kept"]]]
        err = np.abs(rebuilt - original).max()
        if err > 0.05:
            print(f"  {label}: getPos error {err}")
            failures += 1
        failures += verify_mesh(kcl, verts, faces, report["kept"], samples_per_triangle=1 if args.quick else 3,
                                rng=rng, label=f"{label} [{report['size']} bytes, widths {report['widths']}]")
    pa = build_pa([DEFAULT_ROW, {"Floor_code": "Ice", "Sound_code": "Ice"}, {"Wall_code": "NotWallJump"}])
    _, rows = read_pa(pa)
    assert rows[1]["Floor_code"] == 5 and rows[1]["Sound_code"] == 9 and rows[2]["Wall_code"] == 1, rows
    assert len(pa) % 32 == 0
    files = Path(args.disc) if args.disc else DISC_FILES
    if files.exists():
        print("disc planets (rebuilt from their own triangles):")
        names = ["BathtubPlanet", "BirthdayCakePlanet", "BroadBeanPlanet"][:1 if args.quick else 3]
        for name, kcl, pa_data in disc_planets(files, names):
            original = KclServer(kcl)
            assert validate_kcl(kcl) is None
            tris = original.triangles()
            positions = tris.reshape(-1, 3)
            faces = np.arange(len(positions)).reshape(-1, 3)
            attrs = [p[6] for p in original.prisms[1:]]
            report = {}
            data = build_kcl(positions, faces, attrs, thickness=original.thickness, report=report)
            rebuilt = KclServer(data)
            mapping = {i + 1: int(k) + 1 for i, k in enumerate(report["kept"])}
            # Normals agree with the disc's (convention check).
            worst = 0.0
            for i, k in mapping.items():
                for field in range(2, 6):
                    a = np.array(original.nrm[original.prisms[k][field]])
                    b = np.array(rebuilt.nrm[rebuilt.prisms[i][field]])
                    worst = max(worst, 1.0 - float(a @ b))
                worst = max(worst, abs(original.prisms[k][0] - rebuilt.prisms[i][0]) / max(1.0, original.prisms[k][0]))
            print(f"  {name}: {original.count} disc prisms, {report['skipped']} skipped; "
                  f"normals/heights max deviation {worst:.2e}; disc {len(kcl)} bytes, rebuilt {len(data)} bytes")
            if worst > 1e-3:
                failures += 1
            failures += compare_servers(original, rebuilt, mapping, 300 if args.quick else 1500, rng, name)
            failures += verify_mesh(data, positions, faces, report["kept"], samples_per_triangle=1, rng=rng,
                                    label=f"{name} rebuilt")
    else:
        print(f"disc not found at {files}: disc round trip skipped")
    print("selftest:", "ok" if failures == 0 else f"{failures} failures")
    return 0 if failures == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("selftest")
    p.add_argument("--disc", help="extracted disc 'files' folder (default: the Petari disc folder)")
    p.add_argument("--quick", action="store_true")
    p = sub.add_parser("from-obj")
    p.add_argument("obj")
    p.add_argument("out_kcl")
    p.add_argument("out_pa")
    p.add_argument("--scale", type=float, default=1.0, help="multiply positions (100 for Blender meters)")
    p.add_argument("--z-up", action="store_true", help="OBJ is Z-up (Blender 'Up: Z'): convert to the game's Y-up")
    p.add_argument("--floor", default="Normal")
    p.add_argument("--wall", default="Normal")
    p.add_argument("--sound", default="Stone")
    p.add_argument("--camera-through", default="0")
    p.add_argument("--camera-id", default="255")
    p.add_argument("--codes", help="JSON: material name -> {column: code}")
    p.add_argument("--thickness", type=float, default=40.0)
    p.add_argument("--max-triangles", type=int, default=32)
    p.add_argument("--min-cell", type=int, default=8)
    p = sub.add_parser("info")
    p.add_argument("kcl")
    p.add_argument("pa", nargs="?")
    args = parser.parse_args(argv)
    return {"selftest": cmd_selftest, "from-obj": cmd_from_obj, "info": cmd_info}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

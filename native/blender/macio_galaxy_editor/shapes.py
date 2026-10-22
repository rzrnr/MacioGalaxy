"""Wire shapes for areas and gravity, and the stand-in for every other object, in game units.

Sizes follow Whitehole's renderers (AreaShapeRenderer, GravityShapeRenderer: base size 500):
- areas: BaseOriginCube x, z in [-500, 500], y in [0, 1000] (origin at the bottom); CenterOriginCube
  +-500; Sphere radius 500 (scale_x only in the game); Cylinder radius 500, y in [0, 500]; Bowl the
  lower half of the sphere. The shape is chosen by the object database (AreaShape) or the name's
  ending (Cube, Box, Sphere, Cylinder, Bowl); otherwise a 100-unit cube.
- gravity: built from scale, Range, Distant and Obj_arg0..3 for each kind (gravity_shape).
Everything returns (vertices, edges, faces) with vertices as game-space tuples.
"""
import math

SIZE = 500.0
AREA_SUFFIXES = (("baseorigincube", "BaseOriginCube"), ("centerorigincube", "CenterOriginCube"), ("cube", "BaseOriginCube"),
                 ("box", "CenterOriginCube"), ("sphere", "Sphere"), ("cylinder", "Cylinder"), ("bowl", "Bowl"))


class Builder:
    def __init__(self):
        self.verts, self.edges, self.faces = [], [], []

    def point(self, p):
        self.verts.append(tuple(float(c) for c in p))
        return len(self.verts) - 1

    def line(self, a, b):
        self.edges.append((self.point(a), self.point(b)))

    def polyline(self, points, closed=False):
        ids = [self.point(p) for p in points]
        for i in range(len(ids) - (0 if closed else 1)):
            self.edges.append((ids[i], ids[(i + 1) % len(ids)]))

    def box(self, x0, x1, y0, y1, z0, z1, solid=False):
        corners = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
        ids = [self.point(c) for c in corners]
        if solid:
            for quad in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
                self.faces.append(tuple(ids[i] for i in quad))
        else:
            for a, b in ((0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)):
                self.edges.append((ids[a], ids[b]))

    def ring(self, radius, y, segments=48, rx=None, start=0.0, sweep=2 * math.pi, axis="y"):
        """A circle (or arc) around the y axis at height y (axis "y"), or around x/z."""
        rx = radius if rx is None else rx
        closed = abs(sweep - 2 * math.pi) < 1e-6
        count = segments if closed else segments + 1
        points = []
        for i in range(count):
            a = start + sweep * i / segments
            u, v = math.cos(a) * rx, math.sin(a) * radius
            points.append({"y": (u, y, v), "x": (y, u, v), "z": (u, v, y)}[axis])
        self.polyline(points, closed)

    def sphere(self, radius, cy=0.0, lower_only=False):
        for k in range(1, 6):
            angle = math.pi * k / 6 - math.pi / 2
            if lower_only and angle > 0:
                continue
            self.ring(radius * math.cos(angle), cy + radius * math.sin(angle))
        for k in range(4):
            a = math.pi * k / 4
            sweep = math.pi if lower_only else 2 * math.pi
            points = []
            for i in range(25 if lower_only else 48):
                t = (math.pi + sweep * i / (24 if lower_only else 48)) if lower_only else 2 * math.pi * i / 48
                points.append((math.cos(a) * math.cos(t) * radius, cy + math.sin(t) * radius, math.sin(a) * math.cos(t) * radius))
            self.polyline(points, closed=not lower_only)

    def cylinder(self, radius, y0, y1, segments=48):
        self.ring(radius, y0, segments)
        self.ring(radius, y1, segments)
        for k in range(8):
            a = 2 * math.pi * k / 8
            self.line((math.cos(a) * radius, y0, math.sin(a) * radius), (math.cos(a) * radius, y1, math.sin(a) * radius))

    def arrow(self, start, end, head=0.25):
        self.line(start, end)
        d = [e - s for s, e in zip(start, end)]
        back = [e - c * head for e, c in zip(end, d)]
        size = math.sqrt(sum(c * c for c in d)) * head * 0.5
        for off in ((size, 0, 0), (-size, 0, 0), (0, 0, size), (0, 0, -size)):
            self.line(end, [b + o for b, o in zip(back, off)])

    def result(self):
        return self.verts, self.edges, self.faces


def area_shape_name(name: str, database_shape: str | None) -> str:
    if database_shape and database_shape != "Any":
        return database_shape
    lower = name.lower()
    for suffix, shape in AREA_SUFFIXES:
        if lower.endswith(suffix):
            return shape
    return "Dummy"


def area_shape(shape: str):
    """An area's shape at scale 1 (the object's scale stretches it, as in the game for boxes)."""
    b = Builder()
    if shape == "BaseOriginCube":
        b.box(-SIZE, SIZE, 0, 2 * SIZE, -SIZE, SIZE)
    elif shape == "CenterOriginCube":
        b.box(-SIZE, SIZE, -SIZE, SIZE, -SIZE, SIZE)
    elif shape == "Sphere":
        b.sphere(SIZE)
    elif shape == "Cylinder":
        b.cylinder(SIZE, 0, SIZE)
    elif shape == "Bowl":
        b.sphere(SIZE, lower_only=True)
    else:
        b.box(-50, 50, -50, 50, -50, 50)
    return b.result()


def stand_in(kind: str):
    """A small solid box with a nose toward the object's front (+z), for every placed object."""
    b = Builder()
    half = {"startinfo": 50, "generalposinfo": 25, "soundinfo": 25, "debugmoveinfo": 25, "stageobjinfo": 150}.get(kind, 40)
    b.box(-half, half, 0 if kind == "startinfo" else -half, 2 * half if kind == "startinfo" else half, -half, half, solid=True)
    b.arrow((0, 0, half), (0, 0, half * 2.5))
    if kind == "startinfo":
        b.arrow((0, 2 * half, 0), (0, 4 * half, 0))
    return b.result()


def _arg(fields, name, default=-1):
    value = fields.get(name, default)
    return default if value is None else value


def gravity_shape(name: str, fields: dict, scale):
    """A gravity object's range in its own space with its scale applied (true game sizes)."""
    sx, sy, sz = (abs(s) for s in scale)
    rng = float(_arg(fields, "Range", -1.0))
    distant = float(_arg(fields, "Distant", 0.0))
    b = Builder()
    if name == "GlobalPlaneGravityInBox":
        b.box(-SIZE * sx, SIZE * sx, 0, 2 * SIZE * sy, -SIZE * sz, SIZE * sz)
        b.arrow((0, SIZE * sy, 0), (0, 0.2 * SIZE * sy, 0))
    elif name == "GlobalPlaneGravity":
        if rng > 0:
            b.sphere(rng)
            b.arrow((0, 0.5 * rng, 0), (0, -0.5 * rng, 0))
        else:
            b.box(-50, 50, -50, 50, -50, 50)
            b.arrow((0, 100, 0), (0, -100, 0))
    elif name == "GlobalPlaneGravityInCylinder":
        b.cylinder(SIZE * sx, 0, SIZE * sy)
        b.arrow((0, SIZE * sy, 0), (0, 0.2 * SIZE * sy, 0))
    elif name == "GlobalPointGravity":
        if rng > 0:
            b.sphere(rng)
            if distant > 0:
                for k in range(6):
                    a = 2 * math.pi * k / 6
                    b.line((math.cos(a) * rng, 0, math.sin(a) * rng), (math.cos(a) * (rng + distant), 0, math.sin(a) * (rng + distant)))
                b.ring(rng + distant, 0, 64)
        else:
            b.box(-50, 50, -50, 50, -50, 50)
    elif name == "GlobalCubeGravity":
        hx, hy, hz = SIZE * sx, SIZE * sy, SIZE * sz
        b.box(-hx, hx, 0, 2 * hy, -hz, hz)
        if rng > 0:
            b.box(-hx - rng, hx + rng, -rng, 2 * hy + rng, -hz - rng, hz + rng)
    elif name == "GlobalSegmentGravity":
        top = 2 * SIZE * sy
        b.line((0, 0, 0), (0, top, 0))
        if rng > 0:
            b.cylinder(rng, 0, top, 32)
    elif name == "GlobalDiskGravity":
        radius = SIZE * max(sx, sy, sz)
        b.ring(radius, 0, 64)
        if rng > 0:
            b.ring(radius, rng, 64)
            b.ring(radius, -rng, 64)
            b.ring(radius + rng, 0, 64)
    elif name == "GlobalDiskTorusGravity":
        outer = SIZE * max(sx, sy, sz)
        inner = outer - float(_arg(fields, "Obj_arg2", 0))
        b.ring(outer, 0, 64)
        b.ring(max(inner, 0), 0, 64)
        if rng > 0:
            middle = (outer + max(inner, 0)) / 2
            b.ring(middle, rng, 64)
            b.ring(middle, -rng, 64)
            b.ring(outer + rng, 0, 64)
    elif name == "GlobalConeGravity":
        base, height = SIZE * sx, SIZE * sy
        top = max(0.0, float(_arg(fields, "Obj_arg1", 0)) * 0.5)
        b.ring(base, 0, 48)
        if top > 0:
            b.ring(top, height, 48)
        for k in range(8):
            a = 2 * math.pi * k / 8
            b.line((math.cos(a) * base, 0, math.sin(a) * base), (math.cos(a) * top, height, math.sin(a) * top))
        if rng > 0:
            b.ring(base + rng, 0, 48)
    else:  # GlobalWireGravity (follows its path) and anything unknown
        b.box(-50, 50, -50, 50, -50, 50)
    return b.result()

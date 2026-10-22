"""A galaxy in the Blender scene, and back.

Scene layout: a collection "SMG <Galaxy>" with one collection per zone ("<Zone>") holding a collection
per layer ("<Zone> common", "<Zone> layera", ...) and "<Zone> Paths". The main zone places the other
zones: each of its stageobjinfo rows is an empty ("Zone <Name>"); the zone's contents are children of
the one active in the scenario, so moving it moves the zone in the galaxy.

Every placed row is an object with custom properties:
  smg_kind   the table (objinfo, mappartsinfo, areaobjinfo, cameracubeinfo, planetobjinfo, startinfo, ...)
  smg_zone   the zone whose archive holds the row
  smg_row    the row it was read from (-1: new); with smg_table, the table it was read from
  smg_basis  its matrix when read: unchanged, the row keeps its pos/dir/scale bytes
  smg.<field> every other field (name, l_id, Obj_arg0.., switches, ...)
The layer is the layer collection the object is in. Paths are Bézier curves (pnt0 the point, pnt1 the
incoming and pnt2 the outgoing control point, all absolute in the zone); their fields as smg.<field>,
the points' point_arg0..7 in smg_point_args.
"""
import json

import bpy

from . import shapes
from .catalog import KIND_GROUP
from .convert import basis_from_game, flat, game_from_basis, same_matrix, to_blender, to_game, unflat
from .galaxy import LAYERS, TRANSFORM, Path_, PathPoint, Record

PREFIX = "smg."
COLORS = {"objinfo": (1.0, 0.55, 0.1, 1), "mappartsinfo": (0.25, 0.5, 1.0, 1), "childobjinfo": (1.0, 0.8, 0.2, 1),
          "areaobjinfo": (0.2, 0.9, 0.3, 1), "cameracubeinfo": (0.75, 0.3, 1.0, 1), "planetobjinfo": (0.1, 0.85, 0.95, 1),
          "startinfo": (1.0, 0.15, 0.15, 1), "stageobjinfo": (1.0, 1.0, 1.0, 1), "demoobjinfo": (0.9, 0.4, 0.7, 1),
          "soundinfo": (0.6, 0.6, 0.6, 1), "generalposinfo": (0.6, 0.6, 0.6, 1), "debugmoveinfo": (0.5, 0.5, 0.5, 1)}
WIRE = {"areaobjinfo", "cameracubeinfo", "planetobjinfo"}
HIDDEN_KINDS = {"soundinfo", "generalposinfo", "debugmoveinfo", "demoobjinfo"}  # shown, but off at first


# --- meshes ----------------------------------------------------------------------------------


def _mesh(name, geometry, scale=(1.0, 1.0, 1.0)):
    verts, edges, faces = geometry
    sx, sy, sz = (s if abs(s) > 1e-6 else 1.0 for s in scale)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([to_blender((x / sx, y / sy, z / sz)) for x, y, z in verts], edges, faces)
    mesh.update()
    return mesh


def _shared(name, make):
    mesh = bpy.data.meshes.get(name)
    if mesh is None:
        mesh = _mesh(name, make())
        mesh.use_fake_user = False
    return mesh


def mesh_for(kind, values, scale, catalog):
    name = values.get("name", "")
    if kind == "planetobjinfo":
        return _mesh(f"Gravity {name}", shapes.gravity_shape(name, values, scale), scale)
    if kind in ("areaobjinfo", "cameracubeinfo"):
        entry = catalog.entries.get(name) if catalog else None
        shape = shapes.area_shape_name(name, entry["area_shape"] if entry else None)
        return _shared(f"SMG Area {shape}", lambda: shapes.area_shape(shape))
    return _shared(f"SMG Stand-in {kind}", lambda: shapes.stand_in(kind))


def gravity_signature(obj):
    keys = ("name", "Range", "Distant", "Obj_arg0", "Obj_arg1", "Obj_arg2", "Obj_arg3")
    return json.dumps([obj.get(PREFIX + k) for k in keys] + [round(v, 4) for v in obj.scale])


def refresh_gravity(obj):
    """Rebuilds a gravity object's range after its fields or scale changed."""
    signature = gravity_signature(obj)
    if obj.get("smg_shape") == signature:
        return
    values = fields_of(obj)
    scale = (obj.scale.x, obj.scale.z, obj.scale.y)
    old = obj.data
    obj.data = _mesh(f"Gravity {values.get('name', '')}", shapes.gravity_shape(values.get("name", ""), values, scale), scale)
    if old is not None and old.users == 0:
        bpy.data.meshes.remove(old)
    obj["smg_shape"] = signature


def fields_of(obj) -> dict:
    return {key[len(PREFIX):]: obj[key] for key in obj.keys() if key.startswith(PREFIX)}


def _set_fields(obj, values):
    for key, value in values.items():
        if key not in TRANSFORM:
            obj[PREFIX + key] = value


# --- import ----------------------------------------------------------------------------------


def _collection(name, parent):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
    if coll.name not in parent.children:
        parent.children.link(coll)
    return coll


def remove_galaxy(scene, galaxy_name):
    root = bpy.data.collections.get(f"SMG {galaxy_name}")
    if root is None:
        return
    def walk(coll):
        for child in list(coll.children):
            walk(child)
        for obj in list(coll.objects):
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data is not None and data.users == 0:
                (bpy.data.curves if isinstance(data, bpy.types.Curve) else bpy.data.meshes).remove(data)
        bpy.data.collections.remove(coll)
    walk(root)


def layer_collection(root, zone, layer):
    zone_coll = _collection(zone, root)
    coll = _collection(f"{zone} {layer}", zone_coll)
    coll["smg_zone"], coll["smg_layer"] = zone, layer
    return coll


def new_object(name, kind, zone, values, matrix, collection, catalog, parent=None, row=-1, table=None):
    scale = values.get("scale_x", 1.0), values.get("scale_y", 1.0), values.get("scale_z", 1.0)
    obj = bpy.data.objects.new(name, mesh_for(kind, values, scale, catalog))
    collection.objects.link(obj)
    obj["smg_kind"], obj["smg_zone"], obj["smg_row"] = kind, zone, row
    obj["smg_table"] = table or ""
    _set_fields(obj, values)
    obj.parent = parent
    # Quaternions: Blender's own Euler angles hit gimbal lock for some of the game's rotations (dir_x
    # near +-90 in its axes) and lose a few hundredths of a degree there.
    obj.rotation_mode = "QUATERNION"
    obj.matrix_basis = matrix
    obj["smg_basis"] = flat(obj.matrix_basis)  # as stored, for the unchanged test
    obj.color = COLORS.get(kind, (0.7, 0.7, 0.7, 1))
    if kind in WIRE:
        obj.display_type = "WIRE"
        obj.show_in_front = False
    if kind == "planetobjinfo":
        obj["smg_shape"] = gravity_signature(obj)
    return obj


def _matrix(values):
    return basis_from_game([values.get(f"pos_{a}", 0.0) for a in "xyz"], [values.get(f"dir_{a}", 0.0) for a in "xyz"],
                           [values.get(f"scale_{a}", 1.0) for a in "xyz"])


def import_galaxy(context, galaxy, scenario_no, catalog):
    """One galaxy at a time: an open one (any "SMG ..." collection) is replaced."""
    scene = context.scene
    for coll in [c for c in scene.collection.children if c.get("smg_galaxy")]:
        remove_galaxy(scene, coll["smg_galaxy"])
    root = _collection(f"SMG {galaxy.name}", scene.collection)
    root["smg_galaxy"] = galaxy.name
    scenario = galaxy.scenario(scenario_no)
    main = galaxy.zone(galaxy.name)

    # The zones' placements: one empty per stageobjinfo row of the main zone.
    placements = {}
    for record in main.records():
        if record.kind != "stageobjinfo":
            continue
        coll = layer_collection(root, galaxy.name, record.layer)
        obj = new_object(f"Zone {record.values['name']}", "stageobjinfo", galaxy.name, record.values, _matrix(record.values),
                         coll, catalog, row=record.row, table=record.table)
        active = record.layer in scenario.layers(galaxy.name)
        current = placements.get(record.values["name"])
        if current is None or (active and not current[1]):
            placements[record.values["name"]] = (obj, active)

    count = 0
    for zone_name in galaxy.zone_names:
        zone = galaxy.zone(zone_name)
        parent = None if zone_name == galaxy.name else (placements.get(zone_name) or (None,))[0]
        for record in zone.records():
            if record.kind == "stageobjinfo":
                continue
            coll = layer_collection(root, zone_name, record.layer)
            new_object(record.values.get("name", record.kind), record.kind, zone_name, record.values, _matrix(record.values),
                       coll, catalog, parent=parent, row=record.row, table=record.table)
            count += 1
        paths_coll = _collection(f"{zone_name} Paths", _collection(zone_name, root))
        paths_coll["smg_zone"], paths_coll["smg_layer"] = zone_name, "path"
        for path in zone.paths():
            make_path(path, zone_name, paths_coll, parent)
            count += 1
    scene["smg_galaxy"], scene["smg_scenario"] = galaxy.name, scenario_no
    scene["smg_main_origin"] = main.origin
    apply_scenario(scene, galaxy)
    return count


def make_path(path: Path_, zone, collection, parent=None):
    curve = bpy.data.curves.new(path.values.get("name", "Path"), "CURVE")
    curve.dimensions = "3D"
    spline = curve.splines.new("BEZIER")
    points = path.points or [PathPoint({f"pnt{i}_{a}": 0.0 for i in range(3) for a in "xyz"})]
    spline.bezier_points.add(len(points) - 1)
    for bp, point in zip(spline.bezier_points, points):
        v = point.values
        bp.handle_left_type = bp.handle_right_type = "FREE"
        bp.co = to_blender([v[f"pnt0_{a}"] for a in "xyz"])
        bp.handle_left = to_blender([v[f"pnt1_{a}"] for a in "xyz"])
        bp.handle_right = to_blender([v[f"pnt2_{a}"] for a in "xyz"])
    spline.use_cyclic_u = path.values.get("closed") == "CLOSE"
    # Each point's game values with the curve's coordinates as stored (32-bit floats in metres): an
    # unmoved point writes its game values back exactly.
    stored = []
    for bp, point in zip(spline.bezier_points, path.points):
        stored.append({"args": {k: v for k, v in point.values.items() if k.startswith("point_arg")},
                       "game": {k: v for k, v in point.values.items() if k.startswith("pnt")},
                       "curve": [round(c, 7) for vec in (bp.co, bp.handle_left, bp.handle_right) for c in vec]})
    obj = bpy.data.objects.new(f"Path {path.values.get('name', '')}", curve)
    collection.objects.link(obj)
    obj["smg_kind"], obj["smg_zone"], obj["smg_row"] = "path", zone, path.row
    obj["smg_table"] = path.source or ""
    _set_fields(obj, {k: v for k, v in path.values.items() if k not in ("no", "num_pnt")})
    obj["smg_points"] = json.dumps(stored)
    obj.parent = parent
    obj["smg_basis"] = flat(obj.matrix_basis)
    obj.color = (1.0, 0.95, 0.3, 1)
    return obj


def apply_scenario(scene, galaxy):
    """Shows the layers the scenario uses; the others stay in the scene, hidden."""
    root = bpy.data.collections.get(f"SMG {galaxy.name}")
    if root is None:
        return
    scenario = galaxy.scenario(scene.get("smg_scenario", galaxy.scenarios[0].no))
    main_layers = scenario.layers(galaxy.name)
    for zone_coll in root.children:
        zone = zone_coll.name
        active_zone = zone == galaxy.name or scenario.masks.get(zone, 0) != 0 or zone not in scenario.masks
        layers = scenario.layers(zone)
        for coll in zone_coll.children:
            layer = coll.get("smg_layer")
            coll.hide_viewport = not active_zone or (layer not in ("path", None) and layer not in layers)
    for obj in root.all_objects:
        if obj.get("smg_kind") == "stageobjinfo":
            layer = obj.users_collection[0].get("smg_layer") if obj.users_collection else "common"
            obj.hide_set(layer not in main_layers)
        elif obj.get("smg_kind") in HIDDEN_KINDS:
            obj.hide_set(True)


# --- export ----------------------------------------------------------------------------------


def _zone_local(obj):
    """The object's matrix in its zone (its parent is the zone's placement, if any).

    From the parent relation itself (world = parent world . parent inverse . basis), so it needs no
    evaluated world matrices; another parent (one the user chose) goes through the world matrices.
    """
    if obj.parent is None:
        return obj.matrix_basis.copy()
    if obj.parent.get("smg_kind") == "stageobjinfo":
        return obj.matrix_parent_inverse @ obj.matrix_basis
    zone_parent = obj.parent
    while zone_parent is not None and zone_parent.get("smg_kind") != "stageobjinfo":
        zone_parent = zone_parent.parent
    world = obj.matrix_world.copy()
    return zone_parent.matrix_world.inverted() @ world if zone_parent is not None else world


def _layer_of(obj):
    for coll in obj.users_collection:
        if coll.get("smg_layer") in LAYERS:
            return coll["smg_layer"]
    return "common"


def collect(scene, galaxy):
    """Per zone: ({table path: [Record]}, [Path_] or None) from the scene's objects."""
    root = bpy.data.collections.get(f"SMG {galaxy.name}")
    if root is None:
        raise RuntimeError(f"Die Galaxie {galaxy.name} ist nicht in der Szene geöffnet.")
    objects = sorted(root.all_objects, key=lambda o: (o.get("smg_row", -1) < 0, o.get("smg_row", -1), o.name))
    edits = {}
    claimed = set()
    for obj in objects:
        kind, zone = obj.get("smg_kind"), obj.get("smg_zone")
        if not kind or not zone:
            continue
        tables, paths = edits.setdefault(zone, ({}, []))
        values = fields_of(obj)
        matrix = _zone_local(obj)
        if kind == "path":
            paths.append(_path_from(obj, values, matrix))
            continue
        table = f"jmp/{KIND_GROUP.get(kind, 'placement')}/{_layer_of(obj)}/{kind}"
        row = obj.get("smg_row", -1)
        # A duplicate (Shift+D copies the properties) or a moved object is a new row in its table.
        key = (zone, obj.get("smg_table"), row)
        if row < 0 or obj.get("smg_table") != table or key in claimed:
            row = -1
        claimed.add(key)
        original = unflat(obj["smg_basis"]) if "smg_basis" in obj else None
        if row < 0 or original is None or not same_matrix(original, matrix):
            pos, rot, scale = game_from_basis(matrix)
            for i, a in enumerate("xyz"):
                values[f"pos_{a}"], values[f"dir_{a}"], values[f"scale_{a}"] = pos[i], rot[i], scale[i]
        tables.setdefault(table, []).append(Record(zone, table, row, values, obj))
    for zone_name in galaxy.zone_names:
        tables, _ = edits.setdefault(zone_name, ({}, []))
        for table in galaxy.zone(zone_name).table_paths():
            tables.setdefault(table, [])  # every object of a table deleted: an empty table
    for zone, (tables, paths) in edits.items():
        _unique_ids(tables, paths)
    return edits


def _path_from(obj, values, matrix):
    spline = obj.data.splines[0] if obj.data.splines else None
    stored = json.loads(obj.get("smg_points", "[]"))
    unmoved = "smg_basis" in obj and same_matrix(unflat(obj["smg_basis"]), matrix)
    points = []
    if spline is not None:
        bezier = spline.bezier_points if spline.type == "BEZIER" else None
        items = bezier if bezier is not None else spline.points
        for i, p in enumerate(items):
            co = p.co if bezier is not None else p.co.xyz
            left = p.handle_left if bezier is not None else co
            right = p.handle_right if bezier is not None else co
            known = stored[i] if i < len(stored) else None
            curve = [round(c, 7) for vec in (co, left, right) for c in vec]
            if known and unmoved and known.get("curve") == curve:
                point = dict(known["game"])
            else:
                point = {}
                for n, vec in (("0", co), ("1", left), ("2", right)):
                    g = to_game(matrix @ vec)
                    point.update({f"pnt{n}_x": round(g.x, 3), f"pnt{n}_y": round(g.y, 3), f"pnt{n}_z": round(g.z, 3)})
            point.update(known["args"] if known else {f"point_arg{k}": -1 for k in range(8)})
            points.append(PathPoint(point))
        values["closed"] = "CLOSE" if spline.use_cyclic_u else "OPEN"
    return Path_(obj.get("smg_zone"), obj.get("smg_row", -1), values, points, obj.get("smg_table") or None, obj)


def _unique_ids(tables, paths):
    """New rows get an l_id no other row of the zone uses (ObjInfo and MapPartsInfo share one space)."""
    used = {r.values.get("l_id") for records in tables.values() for r in records if r.row >= 0}
    for records in tables.values():
        for r in records:
            if r.row < 0 and r.kind not in ("stageobjinfo", "demoobjinfo", "startinfo", "generalposinfo") and \
                    r.values.get("l_id") in used | {None, -1}:
                r.values["l_id"] = max([i for i in used if isinstance(i, int)] + [0]) + 1
            used.add(r.values.get("l_id"))
    path_ids = {p.values.get("l_id") for p in paths if p.row >= 0}
    for p in paths:
        if p.row < 0 and (p.values.get("l_id") in path_ids or p.values.get("l_id") is None):
            p.values["l_id"] = max([i for i in path_ids if isinstance(i, int)] + [-1]) + 1
        path_ids.add(p.values.get("l_id"))


def rebase(edits, written):
    """After a save: the rows as written are the objects' new originals (row, table, l_id, matrix)."""
    for zone, (tables, paths) in edits.items():
        if zone not in written:
            continue
        for table, records in tables.items():
            for row, record in enumerate(records):
                obj = record.owner
                if obj is None:
                    continue
                obj["smg_row"], obj["smg_table"] = row, table
                if "l_id" in record.values:
                    obj[PREFIX + "l_id"] = record.values["l_id"]
                obj["smg_basis"] = flat(_zone_local(obj))
        for row, path in enumerate(paths):
            obj = path.owner
            if obj is not None:
                obj["smg_row"], obj["smg_table"] = row, f"jmp/path/commonpathpointinfo.{row}"
                obj[PREFIX + "l_id"] = path.values.get("l_id")
                matrix = _zone_local(obj)
                obj["smg_basis"] = flat(matrix)
                spline = obj.data.splines[0]
                obj["smg_points"] = json.dumps([
                    {"args": {k: v for k, v in point.values.items() if k.startswith("point_arg")},
                     "game": {k: v for k, v in point.values.items() if k.startswith("pnt")},
                     "curve": [round(c, 7) for vec in (bp.co, bp.handle_left, bp.handle_right) for c in vec]}
                    for bp, point in zip(spline.bezier_points, path.points)])

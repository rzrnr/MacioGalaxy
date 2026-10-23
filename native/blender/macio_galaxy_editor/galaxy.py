"""A galaxy's stage data as the game sees it: the disc with the enabled mods on top (no Blender here).

Galaxy files (SMG1): StageData/<Galaxy>/<Galaxy>Scenario.arc holds scenariodata.bcsv (one row per
scenario, one column per zone: the zone's layer mask, bit 0 = layera) and zonelist.bcsv; each zone,
the galaxy's main zone included, is StageData/<Zone>.arc. A zone's tables are jmp/<group>/<layer>/<kind>
(group placement, mapparts, start, childobj, generalpos, debug; layer common or layera..layerp) and
its paths jmp/path/commonpathinfo with one point table per path, jmp/path/commonpathpointinfo.<no>.
The main zone places the other zones (jmp/placement/<layer>/stageobjinfo: zone name, pos, dir).

A file comes from the highest-priority enabled mod that has it (mods.txt Folder.<Mod>=on, mod.txt
priority=, then the name), else from the disc: the precedence of native/app/platform_host.cpp.
"""
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "native/tools"))
from rarc_tree import Tree, read_tree, write_tree  # noqa: E402
from stage_edit import Table, jmap_hash  # noqa: E402

USER = Path.home() / "Library/Application Support/Petari"
LAYERS = ["common"] + [f"layer{c}" for c in "abcdefghijklmnop"]
PLACEMENT_GROUPS = ("placement", "mapparts", "start", "childobj", "generalpos", "debug")

# Every field of the SMG1 stage tables (names from Whitehole's hash list; the tables store hashes).
FIELD_NAMES = """name l_id pos_x pos_y pos_z dir_x dir_y dir_z scale_x scale_y scale_z Obj_arg0 Obj_arg1 Obj_arg2
Obj_arg3 Obj_arg4 Obj_arg5 Obj_arg6 Obj_arg7 SW_APPEAR SW_DEAD SW_A SW_B SW_SLEEP CameraSetId MessageId CastId
ViewGroupId ShapeModelNo CommonPath_ID ClippingGroupId GroupId DemoGroupId MapParts_ID MarioNo FollowId Obj_ID
ChildObjId InterpolateIn InterpolateOut Validity ParentID MoveConditionType RotateSpeed RotateAngle RotateAxis
RotateAccelType RotateStopTime RotateType ShadowType SignMotionType PressType FarClip Range Distant Priority Inverse
Power Gravity_type DemoName TimeSheetName PosName Camera_id type closed num_pnt path_arg0 path_arg1 path_arg2
path_arg3 path_arg4 path_arg5 path_arg6 path_arg7 usage no Path_ID point_arg0 point_arg1 point_arg2 point_arg3
point_arg4 point_arg5 point_arg6 point_arg7 pnt0_x pnt0_y pnt0_z pnt1_x pnt1_y pnt1_z pnt2_x pnt2_y pnt2_z id
ScenarioNo ScenarioName PowerStarId AppearPowerStarObj Comet LuigiModeTimer IsHidden ErrorCheck ZoneName Index""".split()
NAME_OF = {jmap_hash(n): n for n in FIELD_NAMES}
TRANSFORM = {f"{p}_{a}" for p in ("pos", "dir", "scale") for a in "xyz"}


def field_names(table: Table):
    """The table's field names in layout order (unknown hashes as 0x...)."""
    return [NAME_OF.get(f[0], f"0x{f[0]:08X}") for f in table.fields]


def row_values(table: Table, row: int) -> dict:
    return {name: table.get(row, name) for name in field_names(table) if not name.startswith("0x")}


# --- the game's files -------------------------------------------------------------------------


@dataclass
class Mod:
    name: str
    root: Path
    priority: int
    enabled: bool


class GameData:
    def __init__(self, user: Path = USER, disc: Path | None = None):
        self.user = Path(user)
        disc = Path(disc) if disc else self.user / "Disc/RMGE01"
        self.disc = disc / "files" if (disc / "files").is_dir() else disc
        self.mods = self._mods()

    def _mods(self):
        states = {}
        mods_txt = self.user / "mods.txt"
        if mods_txt.exists():
            for line in mods_txt.read_text(errors="replace").splitlines():
                m = re.match(r"\s*Folder\.(.+?)\s*=\s*(on|off)\s*$", line)
                if m:
                    states[m.group(1)] = m.group(2) == "on"
        mods = []
        folder = self.user / "mods"
        for root in sorted(folder.iterdir()) if folder.is_dir() else ():
            if not (root / "files").is_dir():
                continue
            priority = 0
            info = root / "mod.txt"
            if info.exists():
                m = re.search(r"^priority\s*=\s*(-?\d+)", info.read_text(errors="replace"), re.M)
                priority = int(m.group(1)) if m else 0
            mods.append(Mod(root.name, root, priority, states.get(root.name, False)))
        mods.sort(key=lambda m: (-m.priority, m.name))
        return mods

    def enabled_mods(self):
        return [m for m in self.mods if m.enabled]

    def locate(self, relative: str):
        """(path, origin) of a file below files/: the winning enabled mod's, else the disc's."""
        for mod in self.enabled_mods():
            path = mod.root / "files" / relative
            if path.exists():
                return path, mod.name
        path = self.disc / relative
        return (path, "disc") if path.exists() else (None, None)

    def read(self, relative: str):
        path, origin = self.locate(relative)
        if path is None:
            raise FileNotFoundError(relative)
        return path.read_bytes(), origin

    def galaxies(self):
        """Galaxy names: StageData/<Name>/<Name>Scenario.arc on the disc or in an enabled mod."""
        names = set()
        for root in [self.disc] + [m.root / "files" for m in self.enabled_mods()]:
            stage = root / "StageData"
            if stage.is_dir():
                names |= {d.name for d in stage.iterdir() if (d / f"{d.name}Scenario.arc").exists()}
        return sorted(names)

    def open(self, galaxy: str) -> "Galaxy":
        return Galaxy(self, galaxy)

    def messages(self, prefix: str, language: str = "UsEnglish") -> dict:
        """Message ID -> text for IDs starting with prefix: the disc's (<language>/MessageData/Message.arc),
        else the enabled mods' messages.txt (the first file that has it, as the game)."""
        out = {}
        path = self.disc / language / "MessageData/Message.arc"
        if path.exists():
            tree = read_tree(path.read_bytes())
            ids = Table(tree.files["messageid.tbl"])
            bmg = tree.files["message.bmg"]
            info, data = _bmg_sections(bmg)
            for r in range(len(ids.rows)):
                label = ids.get(r, "MessageId")
                if label.startswith(prefix):
                    out[label] = _bmg_text(bmg, info, data, ids.get(r, "Index"))
        for mod in self.enabled_mods():
            for name in (f"messages.{language}.txt", "messages.txt"):
                text = mod.root / name
                if not text.exists():
                    continue
                for line in text.read_text(errors="replace").splitlines():
                    key, sep, value = line.partition("=")
                    key = key.strip()
                    if sep and key.startswith(prefix) and not line.lstrip().startswith("#"):
                        out.setdefault(key, value.strip().replace("\\n", " "))
        return out

    def galaxy_names(self) -> dict:
        """Galaxy -> its name in the game (GalaxyName_<Galaxy>), where it has one."""
        names = self.messages("GalaxyName_")
        return {key[len("GalaxyName_"):]: value for key, value in names.items() if value}


def _bmg_sections(bmg: bytes):
    """(INF1 offset, DAT1 data offset) of a BMG message file."""
    at, info, data = 0x20, None, None
    for _ in range(struct.unpack_from(">I", bmg, 12)[0]):
        tag, size = bmg[at:at + 4], struct.unpack_from(">I", bmg, at + 4)[0]
        if tag == b"INF1":
            info = at
        elif tag == b"DAT1":
            data = at + 8
        at += size
    return info, data


def _bmg_text(bmg: bytes, info: int, data: int, index: int) -> str:
    """Message index's text (UTF-16BE), control codes left out."""
    entry_size = struct.unpack_from(">H", bmg, info + 10)[0]
    at = data + struct.unpack_from(">I", bmg, info + 16 + index * entry_size)[0]
    chars = []
    for _ in range(16):  # some messages start with empty characters before their first control code
        if at + 1 < len(bmg) and struct.unpack_from(">H", bmg, at)[0] == 0:
            at += 2
    while at + 1 < len(bmg):
        code = struct.unpack_from(">H", bmg, at)[0]
        if code == 0:
            break
        if code == 0x1A:  # escape: a byte with its whole length follows
            at += max(bmg[at + 2], 3)
            continue
        chars.append(chr(code) if code != 10 else " ")
        at += 2
    return "".join(chars).strip()


# --- galaxies and zones -----------------------------------------------------------------------


@dataclass
class Scenario:
    no: int
    name: str
    masks: dict  # zone -> layer mask (bit 0 layera)

    def layers(self, zone):
        mask = self.masks.get(zone, 0)
        return ["common"] + [LAYERS[1 + i] for i in range(16) if mask & (1 << i)]


class Galaxy:
    def __init__(self, game: GameData, name: str):
        self.game, self.name = game, name
        raw, self.scenario_origin = game.read(f"StageData/{name}/{name}Scenario.arc")
        tree = read_tree(raw)
        files = {p.lower(): d for p, d in tree.files.items()}
        zones = Table(files["zonelist.bcsv"])
        self.zone_names = [zones.get(r, "ZoneName") for r in range(len(zones.rows))]
        data = Table(files["scenariodata.bcsv"])
        self.scenarios = []
        for r in range(len(data.rows)):
            masks = {z: data.get(r, z) for z in self.zone_names if data.has(z)}
            self.scenarios.append(Scenario(data.get(r, "ScenarioNo"), data.get(r, "ScenarioName"), masks))
        self.scenarios.sort(key=lambda s: s.no)
        self._zones = {}

    def zone(self, name: str) -> "Zone":
        if name not in self._zones:
            raw, origin = self.game.read(f"StageData/{name}.arc")
            self._zones[name] = Zone(name, read_tree(raw), origin)
        return self._zones[name]

    def scenario(self, no: int) -> Scenario:
        return next(s for s in self.scenarios if s.no == no)


@dataclass
class Record:
    """One row of a placement table."""
    zone: str
    table: str          # path in the zone archive, e.g. jmp/placement/layera/objinfo
    row: int            # index in that table (-1: new)
    values: dict        # field name -> value
    owner: object = None  # the editor's object for it

    @property
    def group(self):
        return self.table.split("/")[1]

    @property
    def layer(self):
        return self.table.split("/")[2]

    @property
    def kind(self):
        return self.table.split("/")[-1]


@dataclass
class PathPoint:
    values: dict  # pnt0_x.. pnt2_z, point_arg0..7, id


@dataclass
class Path_:
    zone: str
    row: int
    values: dict              # commonpathinfo fields (name, type, closed, num_pnt, l_id, no, ...)
    points: list = field(default_factory=list)
    source: str | None = None  # the point table read (its layout is reused when written)
    owner: object = None


class Zone:
    def __init__(self, name: str, tree: Tree, origin: str):
        self.name, self.tree, self.origin = name, tree, origin
        self._tables = {}

    def table(self, path: str) -> Table:
        if path not in self._tables:
            self._tables[path] = Table(self.tree.files[path])
        return self._tables[path]

    def table_paths(self):
        for path in self.tree.files:
            parts = path.split("/")
            if len(parts) == 4 and parts[0] == "jmp" and parts[1] in PLACEMENT_GROUPS and parts[2] in LAYERS:
                yield path

    def records(self):
        for path in self.table_paths():
            table = self.table(path)
            for r in range(len(table.rows)):
                yield Record(self.name, path, r, row_values(table, r))

    def paths(self):
        if "jmp/path/commonpathinfo" not in self.tree.files:
            return []
        info = self.table("jmp/path/commonpathinfo")
        out = []
        for r in range(len(info.rows)):
            path = Path_(self.name, r, row_values(info, r))
            path.source = f"jmp/path/commonpathpointinfo.{path.values['no']}"
            points = self.tree.files.get(path.source)
            if points is not None:
                table = Table(points)
                path.points = [PathPoint(row_values(table, i)) for i in range(len(table.rows))]
            out.append(path)
        return out

    # --- writing ---

    def _row_for(self, table: Table, base: bytes | None, values: dict) -> bytearray:
        record = bytearray(base) if base is not None else bytearray(table.entry_size)
        table.rows.append(record)
        index = len(table.rows) - 1
        for name in field_names(table):
            # Unchanged fields keep their bytes (a string stays at its own offset).
            if name in values and (base is None or table.get(index, name) != values[name]):
                table.set(index, name, values[name])
        table.rows.pop()
        return record

    def rebuild(self, records_by_table: dict, paths: list | None) -> bytes:
        """The zone archive with the given tables' rows replaced (plain RARC).

        records_by_table: table path -> [Record] in the wanted order; a Record with row >= 0 starts
        from that original row (fields it does not set keep their bytes), a new one from zeros.
        Tables not given stay as they are. paths: [Path_] replaces every path (None: keep them).
        """
        files = dict(self.tree.files)
        for path, records in records_by_table.items():
            if path not in self.tree.files and not records:
                continue
            source = self.tree.files.get(path) or self._empty_like(path)
            original = Table(source)
            table = Table(source)
            rows = []
            for record in records:
                base = original.rows[record.row] if 0 <= record.row < len(original.rows) else None
                rows.append(self._row_for(table, base, record.values))
            table.rows = rows
            files[path] = table.build()
        if paths is not None:
            files = self._rebuild_paths(files, paths)
        tree = Tree(self.tree.root, list(self.tree.folders), files, dict(self.tree.flags), self.tree.sync)
        return write_tree(tree)

    def _empty_like(self, path: str) -> bytes:
        """An empty table for a layer the zone does not have yet, laid out like the zone's others."""
        kind = path.split("/")[-1]
        for name, data in self.tree.files.items():
            if name.split("/")[-1] == kind:
                table = Table(data)
                table.rows, table.strings = [], bytearray()
                return table.build()
        raise ValueError(f"{self.name}: no {kind} table to copy the layout from")

    def _point_template(self, source=None):
        """A point table's layout: the path's own, else any numbered one (without its strings)."""
        if source in self.tree.files:
            return self.tree.files[source]
        for name, data in self.tree.files.items():
            if re.fullmatch(r"jmp/path/commonpathpointinfo\.\d+", name):
                table = Table(data)
                table.rows, table.strings = [], bytearray()
                return table.build()
        raise ValueError(f"{self.name}: no path point table to copy the layout from")

    def _rebuild_paths(self, files: dict, paths: list) -> dict:
        if "jmp/path/commonpathinfo" not in self.tree.files:
            if paths:
                raise ValueError(f"{self.name}: the zone has no path table")
            return files
        info_original = Table(self.tree.files["jmp/path/commonpathinfo"])
        info = Table(self.tree.files["jmp/path/commonpathinfo"])
        for name in [n for n in files if re.fullmatch(r"jmp/path/commonpathpointinfo\.\d+", n)]:
            del files[name]
        rows = []
        for no, path in enumerate(paths):
            values = dict(path.values, no=no, num_pnt=len(path.points))
            base = info_original.rows[path.row] if 0 <= path.row < len(info_original.rows) else None
            rows.append(self._row_for(info, base, values))
            points = Table(self._point_template(path.source))
            point_rows = []
            for i, point in enumerate(path.points):
                point_rows.append(self._row_for(points, None, dict(point.values, id=i)))
            points.rows = point_rows
            files[f"jmp/path/commonpathpointinfo.{no}"] = points.build()
        info.rows = rows
        files["jmp/path/commonpathinfo"] = info.build()
        return files

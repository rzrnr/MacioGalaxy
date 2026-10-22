"""The objects one can place: names, their table, a description, and working default values.

Two sources, both local:
- Whitehole's object database (objectdb.json, the SMGCommunity galaxydatabase that Whitehole keeps in
  its data folder): display names, notes, categories, the table (ListSMG1), an area's shape, and what
  each Obj_arg means (its class's Parameters). Used when the file is there.
- The disc: every object placed in any zone, with the values of its first placement as defaults
  (so a new object starts with arguments that work). Built once from the user's disc and cached in
  ~/Library/Caches/MacioGalaxyEditor/catalog.json; nothing of the disc goes anywhere else.
"""
import json
from pathlib import Path

from .galaxy import TRANSFORM, GameData, row_values

CACHE = Path.home() / "Library/Caches/MacioGalaxyEditor"
LIST_TO_KIND = {"ObjInfo": "objinfo", "MapPartsInfo": "mappartsinfo", "AreaObjInfo": "areaobjinfo",
                "PlanetObjInfo": "planetobjinfo", "CameraCubeInfo": "cameracubeinfo", "ChildObjInfo": "childobjinfo",
                "DemoObjInfo": "demoobjinfo", "StartInfo": "startinfo", "SoundInfo": "soundinfo",
                "GeneralPosInfo": "generalposinfo"}
KIND_GROUP = {"objinfo": "placement", "areaobjinfo": "placement", "cameracubeinfo": "placement", "planetobjinfo": "placement",
              "demoobjinfo": "placement", "soundinfo": "placement", "stageobjinfo": "placement", "mappartsinfo": "mapparts",
              "startinfo": "start", "childobjinfo": "childobj", "generalposinfo": "generalpos", "debugmoveinfo": "debug"}
KIND_LABEL = {"objinfo": "Objekt", "mappartsinfo": "Map-Teil", "areaobjinfo": "Area", "cameracubeinfo": "Kamera-Area",
              "planetobjinfo": "Gravity", "startinfo": "Startpunkt", "childobjinfo": "Kind-Objekt", "demoobjinfo": "Demo",
              "soundinfo": "Sound", "generalposinfo": "Position", "debugmoveinfo": "Debug", "stageobjinfo": "Zone"}
# Whitehole's defaults for a new row where the disc has no example (GravityObj, AreaObj, CameraObj, ...).
DEFAULTS = {"planetobjinfo": {"Range": -1.0, "Distant": 0.0, "Priority": 0, "Inverse": -1, "Power": "Normal",
                              "Gravity_type": "Normal"},
            "areaobjinfo": {"ChildObjId": 0}, "cameracubeinfo": {"ChildObjId": 0, "Validity": "Valid"},
            "mappartsinfo": {k: 0 for k in ("MoveConditionType", "RotateSpeed", "RotateAngle", "RotateAxis", "RotateAccelType",
                                            "RotateStopTime", "RotateType", "ShadowType", "SignMotionType", "PressType")},
            "startinfo": {"MarioNo": 0}, "generalposinfo": {"PosName": "undefined"},
            "demoobjinfo": {"DemoName": "undefined", "TimeSheetName": "undefined"}}


def objectdb_path():
    return Path(__file__).resolve().parents[4] / "Whitehole/src/dist/data/objectdb.json"


class Catalog:
    def __init__(self, game: GameData, objectdb: Path | None = None):
        self.entries = {}   # name -> {kind, label, category, notes, area_shape, example, count}
        self.classes = {}   # class name -> parameters
        self._load_objectdb(objectdb or objectdb_path())
        self._load_disc(game)

    def _load_objectdb(self, path: Path):
        if not path.exists():
            return
        data = json.loads(path.read_text())
        categories = {c["Key"]: c["Description"] for c in data.get("Categories", [])}
        self.classes = {c["InternalName"]: c.get("Parameters", {}) for c in data.get("Classes", [])}
        for obj in data.get("Objects", []):
            if not obj.get("Games", 0) & 1:
                continue
            self.entries[obj["InternalName"]] = {
                "kind": LIST_TO_KIND.get(obj.get("ListSMG1", "ObjInfo"), "objinfo"), "label": obj.get("Name") or obj["InternalName"],
                "category": categories.get(obj.get("Category"), obj.get("Category") or ""), "notes": obj.get("Notes", ""),
                "area_shape": obj.get("AreaShape", "Any"), "class": obj.get("ClassNameSMG1") or obj["InternalName"],
                "example": None, "count": 0, "unused": bool(obj.get("IsUnused"))}

    def _load_disc(self, game: GameData):
        cache = CACHE / "catalog.json"
        if cache.exists():
            examples = json.loads(cache.read_text())
        else:
            examples = {}
            for path in sorted((game.disc / "StageData").glob("*.arc")):
                from .galaxy import Zone, read_tree
                zone = Zone(path.stem, read_tree(path.read_bytes()), "disc")
                for table_path in zone.table_paths():
                    kind = table_path.split("/")[-1]
                    if kind == "stageobjinfo":
                        continue
                    table = zone.table(table_path)
                    for r in range(len(table.rows)):
                        values = row_values(table, r)
                        name = values.get("name")
                        entry = examples.setdefault(f"{kind}/{name}", {"count": 0, "values": None})
                        entry["count"] += 1
                        if entry["values"] is None:
                            entry["values"] = {k: v for k, v in values.items() if k not in TRANSFORM and k != "l_id"}
            CACHE.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(examples))
        for key, example in examples.items():
            kind, _, name = key.partition("/")
            entry = self.entries.get(name)
            if entry is None:
                entry = self.entries[name] = {"kind": kind, "label": name, "category": "", "notes": "", "area_shape": "Any",
                                              "class": name, "example": None, "count": 0, "unused": False}
            if entry["kind"] == kind or entry["example"] is None:
                entry["kind"] = kind
                entry["example"] = example["values"]
                entry["count"] += example["count"]

    def names(self, kind: str | None = None):
        """Names sorted by how often the game uses them (unused ones last)."""
        items = [(n, e) for n, e in self.entries.items() if kind is None or e["kind"] == kind]
        return [n for n, e in sorted(items, key=lambda i: (i[1]["unused"], -i[1]["count"], i[0].lower()))]

    def defaults(self, name: str) -> dict:
        entry = self.entries.get(name, {"kind": "objinfo", "example": None})
        values = dict(DEFAULTS.get(entry["kind"], {}))
        if entry.get("example"):
            values.update(entry["example"])
        values["name"] = name
        return values

    def parameter(self, name: str, field: str):
        """(label, description, values) of an object's field from the database, or None."""
        entry = self.entries.get(name)
        params = self.classes.get(entry["class"], {}) if entry else {}
        info = params.get(field)
        if not info:
            return None
        values = ", ".join(f"{v['Value']}: {v['Notes']}" for v in info.get("Values", []))
        return info.get("Name") or field, info.get("Description", ""), values

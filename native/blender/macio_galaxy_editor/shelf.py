"""The object palette as a strip at the bottom of the 3D view (an asset shelf, like BlenderKit's bar).

It shows the "Mario Galaxy" asset library (assets.py) while the Galaxie workspace has a galaxy open.
A click chooses the object for the Setzen tool and switches to that tool (one choice for the whole
editor); dragging an object onto a planet places it there (assets.adopt_dropped). The shelf's own
search, size and catalog tabs (Objekte, Levelteile, Schwerkraft, ...) are Blender's.
"""
import json

import bpy
from bpy.props import EnumProperty, StringProperty

from . import assets

_names = {}
SHELF_KINDS = {"objinfo", "mappartsinfo", "planetobjinfo", "childobjinfo"}


def object_name(asset_name: str):
    """The game's object name for an asset name (names.json, written with the library)."""
    if not _names and assets.NAMES.exists():
        _names.update(json.loads(assets.NAMES.read_text()))
    return _names.get(asset_name)


class MGE_OT_shelf_choose(bpy.types.Operator):
    bl_idname = "mge.shelf_choose"
    bl_label = "Objekt wählen"
    bl_description = "Dieses Objekt mit dem Setzen-Werkzeug auf einen Planeten setzen"
    bl_options = {"INTERNAL"}
    # Filled by the asset shelf (the asset reference).
    asset_library_type: EnumProperty(items=[("ALL", "", ""), ("LOCAL", "", ""), ("ESSENTIALS", "", ""), ("CUSTOM", "", "")],
                                     options={"SKIP_SAVE"})
    asset_library_identifier: StringProperty(options={"SKIP_SAVE"})
    relative_asset_identifier: StringProperty(options={"SKIP_SAVE"})

    def execute(self, context):
        asset_name = self.relative_asset_identifier.rsplit("/", 1)[-1]
        name = object_name(asset_name)
        if name is None:
            self.report({"WARNING"}, f"Unbekanntes Objekt {asset_name!r}: Objekt-Palette neu aufbauen")
            return {"CANCELLED"}
        context.window_manager.mge_tool_object = name
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                region = next(r for r in area.regions if r.type == "WINDOW")
                with context.temp_override(area=area, region=region):
                    bpy.ops.wm.tool_set_by_id(name="mge.tool_place")
                break
        self.report({"INFO"}, f"{asset_name}: auf einen Planeten klicken (oder hineinziehen)")
        return {"FINISHED"}


class MGE_AST_palette(bpy.types.AssetShelf):
    bl_space_type = "VIEW_3D"
    bl_idname = "MGE_AST_palette"
    bl_options = {"DEFAULT_VISIBLE"}
    bl_default_preview_size = 72
    bl_activate_operator = MGE_OT_shelf_choose.bl_idname

    @classmethod
    def poll(cls, context):
        return bool(context.scene.get("smg_galaxy")) and context.workspace is not None and \
            context.workspace.name == "Galaxie" and context.mode == "OBJECT"

    @classmethod
    def asset_poll(cls, asset):
        """The palette's objects: placeable objects, level parts and gravity (areas, cameras and the rest
        are in the Asset Browser and the Setzen tool's search)."""
        if asset.id_type != "OBJECT" or "MacioGalaxyEditor" not in (asset.full_library_path or ""):
            return False
        tags = {tag.name for tag in asset.metadata.tags}
        return bool(tags & SHELF_KINDS)


CLASSES = (MGE_OT_shelf_choose, MGE_AST_palette)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    _names.clear()

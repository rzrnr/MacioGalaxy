"""The editor's own workspace "Galaxie", beside Layout, Modeling and the others.

Made from a copy of the Layout workspace (else the current one), its areas turned to the editor's
work: the 3D view with the toolbar (the editor's tools), the sidebar on the "Galaxie" tab, the object
palette as its shelf (shelf.py) and the HUD (hud.py) over a space-blue background (the viewport's own
colour; the theme is not touched), and the Outliner, collections only, as the zone and layer tree; the
Properties editor and the timeline closed. The top bar gets the menus "Galaxie" and
"Spiel" while this workspace is active.
"""
import sys

import bpy

NAME = "Galaxie"
SPACE_BLUE = (0.025, 0.035, 0.08)


def editor():
    return sys.modules[__package__]


def configure(window):
    """Turns the active workspace's areas into the Galaxie layout."""
    screen = window.screen
    for area in screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces[0]
            space.show_region_ui = True
            space.show_region_toolbar = True
            space.shading.type = "SOLID"
            space.shading.color_type = "TEXTURE"
            space.shading.wireframe_color_type = "OBJECT"
            space.shading.background_type = "VIEWPORT"
            space.shading.background_color = SPACE_BLUE
            space.overlay.show_floor = False
            space.overlay.show_axis_x = space.overlay.show_axis_y = False
            space.clip_end = max(space.clip_end, 20000.0)
    # The Properties editor and the timeline go: the 3D view takes the height (the object palette is
    # its shelf at the bottom, shelf.py) and the zone tree (Outliner, collections only) the right column.
    for area in list(screen.areas):
        if area.type in ("PROPERTIES", "DOPESHEET_EDITOR", "TIMELINE"):
            with bpy.context.temp_override(window=window, screen=screen, area=area):
                bpy.ops.screen.area_close()
    for area in screen.areas:
        if area.type == "VIEW_3D":
            try:
                area.spaces[0].show_region_asset_shelf = True
            except AttributeError:
                pass  # read-only until the shelf is available (it shows by itself: DEFAULT_VISIBLE)
            area.spaces[0].overlay.show_text = False  # the HUD (hud.py) says where you are
        elif area.type == "OUTLINER":
            area.spaces[0].use_filter_object = False
    bpy.app.timers.register(lambda: _palette(window), first_interval=0.5)


def _palette(window):
    """The sidebar on the Galaxie tab once it has been drawn (before, the tab cannot be set)."""
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            for region in area.regions:
                if region.type == "UI":
                    try:
                        region.active_panel_category = "Galaxie"
                    except AttributeError:
                        return 0.3  # not drawn yet: try again
    return None


class MGE_OT_workspace(bpy.types.Operator):
    bl_idname = "mge.workspace"
    bl_label = "Galaxie-Arbeitsbereich"
    bl_description = "Den Arbeitsbereich \"Galaxie\" öffnen (beim ersten Mal anlegen: eine Kopie von Layout, für die Galaxie-Arbeit eingerichtet)"

    def execute(self, context):
        window = context.window
        existing = bpy.data.workspaces.get(NAME)
        if existing is not None:
            window.workspace = existing
            return {"FINISHED"}
        from . import assets
        if assets.BLEND.exists():
            assets.register_library(context)
        base = bpy.data.workspaces.get("Layout")
        if base is not None and window.workspace != base:
            window.workspace = base
            # The switch takes effect after this event; duplicate in the next one.
            bpy.app.timers.register(lambda: _duplicate(window), first_interval=0.05)
        else:
            _duplicate(window)
        return {"FINISHED"}


def _duplicate(window):
    with bpy.context.temp_override(window=window, screen=window.screen):
        bpy.ops.workspace.duplicate()
    bpy.app.timers.register(lambda: _finish(window), first_interval=0.05)
    return None


def _finish(window):
    workspace = window.workspace
    workspace.name = NAME
    configure(window)
    return None


class MGE_MT_galaxy(bpy.types.Menu):
    bl_label = "Galaxie"
    bl_idname = "MGE_MT_galaxy"

    def draw(self, context):
        layout = self.layout
        layout.operator("mge.open_galaxy", text="Gewählte Galaxie öffnen", icon="FILE_FOLDER")
        layout.operator("mge.save_mod", text="Als Mod speichern", icon="FILE_TICK")
        layout.separator()
        layout.operator("mge.build_assets", text="Objekt-Palette aufbauen", icon="ASSET_MANAGER")
        layout.operator("mge.thumbnails", text="Vorschaubilder erzeugen", icon="IMAGE_DATA")


class MGE_MT_game(bpy.types.Menu):
    bl_label = "Spiel"
    bl_idname = "MGE_MT_game"

    def draw(self, context):
        layout = self.layout
        layout.operator("mge.preview", text="Vorschau (unsichtbar)", icon="RENDER_STILL")
        layout.prop(context.scene, "mge_warp", text="Vorschau am Mario-Start")
        layout.separator()
        layout.operator("mge.play", text="Im Spiel starten", icon="PLAY")


def _topbar(self, context):
    if context.workspace is not None and context.workspace.name == NAME:
        self.layout.menu(MGE_MT_galaxy.bl_idname)
        self.layout.menu(MGE_MT_game.bl_idname)


CLASSES = (MGE_OT_workspace, MGE_MT_galaxy, MGE_MT_game)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_editor_menus.append(_topbar)


def unregister():
    bpy.types.TOPBAR_MT_editor_menus.remove(_topbar)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

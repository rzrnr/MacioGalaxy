"""The editor's own workspace "Galaxie", beside Layout, Modeling and the others.

Made from a copy of the Layout workspace (else the current one), its areas turned to the editor's
work: the 3D view with the toolbar (the editor's tools), the sidebar on the "Galaxie" tab, the object
palette as its shelf (shelf.py) over a space-blue background (the viewport's own colour; the theme is
not touched), and Blender's Outliner beside it; the Properties editor and the timeline closed. While
this workspace is active, the 3D view's header holds the galaxy (its library) and the mission, the
tool header Speichern, Testspielen and a switch per kind drawn, and the top bar the menus "Galaxie"
and "Spiel". A workspace from an older layout (LAYOUT) is made again when it is opened.
"""
import sys

import bpy

NAME = "Galaxie"
LAYOUT = 2  # 2: the Outliner stays
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
    # its shelf at the bottom, shelf.py), the Outliner the right column.
    for area in list(screen.areas):
        if area.type in ("PROPERTIES", "DOPESHEET_EDITOR", "TIMELINE"):
            with bpy.context.temp_override(window=window, screen=screen, area=area):
                bpy.ops.screen.area_close()
    for area in screen.areas:
        if area.type == "VIEW_3D":
            area.spaces[0].overlay.show_text = False  # the header names the galaxy and mission
    window.workspace["mge_layout"] = LAYOUT
    bpy.app.timers.register(lambda: _palette(window), first_interval=0.5)


def _palette(window, tries=[0]):
    """The sidebar on the Galaxie tab and the object palette shown, once the 3D view has been drawn
    (before, the tab cannot be set, and showing a region of an area not yet set up crashed Blender in
    ED_area_init: the first workspace made while Blender was in the background)."""
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            for region in area.regions:
                if region.type == "UI":
                    try:
                        region.active_panel_category = "Galaxie"
                    except (AttributeError, TypeError):  # not drawn yet, or its tabs not there yet
                        tries[0] += 1
                        return 0.3 if tries[0] < 40 else None
            try:
                with bpy.context.temp_override(window=window, screen=window.screen, area=area):
                    area.spaces[0].show_region_asset_shelf = True
            except AttributeError:
                pass  # read-only until the shelf is available (it shows by itself: DEFAULT_VISIBLE)
    tries[0] = 0
    return None


class MGE_OT_workspace(bpy.types.Operator):
    bl_idname = "mge.workspace"
    bl_label = "Galaxie-Arbeitsbereich"
    bl_description = "Den Arbeitsbereich \"Galaxie\" öffnen (beim ersten Mal anlegen: eine Kopie von Layout, für die Galaxie-Arbeit eingerichtet)"

    def execute(self, context):
        window = context.window
        from . import assets
        if assets.BLEND.exists():
            assets.register_library(context)
            if assets.stale() and not bpy.app.background:
                bpy.ops.mge.build_assets()  # an older palette: rebuilt in the background
        existing = bpy.data.workspaces.get(NAME)
        if existing is not None and existing.get("mge_layout", 1) < LAYOUT:
            bpy.app.timers.register(_rebuild(window, existing), first_interval=0.05)
            return {"FINISHED"}
        if existing is not None:
            window.workspace = existing
            if not context.scene.get("smg_galaxy") and not bpy.app.background:
                from . import library
                library.open_soon(window)
            return {"FINISHED"}
        base = bpy.data.workspaces.get("Layout")
        if base is not None and window.workspace != base:
            window.workspace = base
            # The switch takes effect after this event; duplicate in the next one.
            bpy.app.timers.register(lambda: _duplicate(window), first_interval=0.05)
        else:
            _duplicate(window)
        return {"FINISHED"}


def _rebuild(window, old):
    """A workspace of an older layout: deleted, then made again from Layout (one step per timer tick,
    as a workspace switch takes effect after the event)."""
    def steps():
        window.workspace = old
        yield
        with bpy.context.temp_override(window=window, screen=window.screen):
            bpy.ops.workspace.delete()
        yield
        base = bpy.data.workspaces.get("Layout")
        if base is not None:
            window.workspace = base
        yield
        _duplicate(window)
    it = steps()

    def tick():
        try:
            next(it)
        except StopIteration:
            return None
        return 0.05
    return tick


def _duplicate(window):
    with bpy.context.temp_override(window=window, screen=window.screen):
        bpy.ops.workspace.duplicate()
    bpy.app.timers.register(lambda: _finish(window), first_interval=0.05)
    return None


def _finish(window):
    workspace = window.workspace
    workspace.name = NAME
    with bpy.context.temp_override(window=window):
        editor()._galaxy_scene(bpy.context)  # an empty galaxy scene, not the startup cube
    with bpy.context.temp_override(window=window, screen=window.screen):
        configure(window)
    if not window.scene.get("smg_galaxy") and not bpy.app.background:
        from . import library
        library.open_soon(window)
    return None


class MGE_MT_galaxy(bpy.types.Menu):
    bl_label = "Galaxie"
    bl_idname = "MGE_MT_galaxy"

    def draw(self, context):
        layout = self.layout
        layout.operator("mge.library", text="Galaxie wählen …", icon="WORLD")
        layout.operator("mge.save_mod", text="Als Mod speichern", icon="FILE_TICK")
        layout.separator()
        layout.operator("mge.build_assets", text="Objekt-Palette aufbauen", icon="ASSET_MANAGER")
        layout.operator("mge.thumbnails", text="Vorschaubilder erzeugen", icon="IMAGE_DATA")


class MGE_MT_game(bpy.types.Menu):
    bl_label = "Spiel"
    bl_idname = "MGE_MT_game"

    def draw(self, context):
        layout = self.layout
        layout.operator("mge.testplay", text="Testspielen (F5)", icon="PLAY")
        layout.operator("mge.testbed_show", text="Testspiel-Fenster zeigen", icon="WINDOW")
        layout.operator("mge.testbed_stop", text="Testspiel beenden", icon="CANCEL")
        layout.prop(context.scene, "mge_warp")
        layout.separator()
        layout.operator("mge.preview", text="Automatisch testen", icon="RENDER_STILL")
        layout.operator("mge.play", text="Im ganzen Spiel spielen", icon="WORLD")


def _ours(context):
    return context.workspace is not None and context.workspace.name == NAME


def _header(self, context):
    """The 3D view's header: the galaxy (a click: the library) and its mission."""
    if not _ours(context):
        return
    core, scene = editor(), context.scene
    galaxy = scene.get("smg_galaxy")
    row = self.layout.row(align=True)
    title = core.galaxy_names(scene).get(galaxy, galaxy) if galaxy else "Galaxie wählen"
    row.operator("mge.library", text=title, icon="WORLD")
    if galaxy:
        row.prop(scene, "mge_scenario", text="")


def _tool_header(self, context):
    """The tool header: Speichern, Testspielen and a switch per kind drawn, in its colour (the kind's
    name in its tooltip: the colours are the outlines' in the view)."""
    if not _ours(context) or not context.scene.get("smg_galaxy"):
        return
    core, scene, layout = editor(), context.scene, self.layout
    row = layout.row(align=True)
    row.alert = bool(scene.get("mge_dirty"))  # unsaved changes
    row.operator("mge.save_mod", text="", icon="FILE_TICK")
    row = layout.row(align=True)
    starting = core.game_io.running
    status = core.game_io.testbed_status_known()
    if starting is not None and not starting.done and starting.mode == "launch":
        row.enabled = False
        row.operator("mge.testplay", text="Startet …", icon="SORTTIME")
    else:
        row.operator("mge.testplay", text="Testspielen", icon="PLAY", depress=bool(status))
    if status:
        row.operator("mge.testbed_stop", text="", icon="X")
    ui = core.ui
    row = layout.row(align=True)
    for key, label, icon in ui.GROUP_LABELS:
        swatch = ui.swatch_icon(key)
        if swatch:
            row.prop(scene, f"mge_show_{key}", text="", icon_value=swatch, toggle=True)
        else:
            row.prop(scene, f"mge_show_{key}", text="", icon=icon, toggle=True)


def _topbar(self, context):
    if context.workspace is not None and context.workspace.name == NAME:
        self.layout.menu(MGE_MT_galaxy.bl_idname)
        self.layout.menu(MGE_MT_game.bl_idname)


CLASSES = (MGE_OT_workspace, MGE_MT_galaxy, MGE_MT_game)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_editor_menus.append(_topbar)
    bpy.types.VIEW3D_HT_header.append(_header)
    bpy.types.VIEW3D_HT_tool_header.append(_tool_header)


def unregister():
    bpy.types.VIEW3D_HT_tool_header.remove(_tool_header)
    bpy.types.VIEW3D_HT_header.remove(_header)
    bpy.types.TOPBAR_MT_editor_menus.remove(_topbar)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

"""The galaxy library: a window in the middle of the screen with every galaxy as a picture, like a
level select. Opened from the header's galaxy button, and by itself when the workspace opens without
a galaxy.

The pictures are the galaxies' dome miniatures (ObjectData/Mini<Galaxy>.arc, the disc's or a mod's),
rendered once by thumbnails.py in the background; a galaxy without one shows a globe. Groups: the
mods' galaxies (galaxy.json), the galaxies with a miniature, then the rest (the hubs, the small
galaxies and the trials). The search field narrows them by the name in the game or the internal one.
"""
import os
import sys

import bpy
from bpy.props import StringProperty

COLUMNS = 7
# Blender's globe icon as an icon value, for a galaxy without a picture.
GLOBE = bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items["WORLD"].value
PICTURE = 4.2  # the picture's size, in Blender's icon units


def editor():
    return sys.modules[__package__]


def _groups(scene, search):
    """[(title, [galaxy])] for the search text."""
    core = editor()
    game = core.game_data(scene)
    names = core.galaxy_names(scene)
    registry = game.registry()
    text = search.lower().strip()
    found = [g for g in game.galaxies() if not text or text in g.lower() or text in names.get(g, "").lower()]
    by_name = sorted(found, key=lambda g: names.get(g, g).lower())
    mods = [g for g in by_name if g in registry]
    pictured = [g for g in by_name if g not in registry and core.ui.thumbs().icon(f"Mini{g}")]
    rest = [g for g in by_name if g not in registry and g not in pictured]
    return [("Mod-Galaxien", mods), ("Galaxien", pictured), ("Weitere", rest)]


def _short_names(scene):
    key = ("short_names", scene.mge_user)
    cache = editor()._cache
    if key not in cache:
        found = editor().game_data(scene).messages("GalaxyNameShort_")
        cache[key] = {k[len("GalaxyNameShort_"):]: v for k, v in found.items() if v}
    return cache[key]


def render_missing(scene):
    """Starts rendering the miniature pictures that are missing (once; thumbnails.py's background run)."""
    core = editor()
    thumbs = core.ui.thumbs()
    game = core.game_data(scene)
    items = []
    for galaxy in game.galaxies():
        archive = f"Mini{galaxy}"
        if game.locate(f"ObjectData/{archive}.arc")[0] is not None:
            items.append((archive, {"name": archive}, archive))
    if thumbs.missing(items) and not thumbs.running():
        thumbs.start(items, game.user)


class MGE_OT_library(bpy.types.Operator):
    bl_idname = "mge.library"
    bl_label = "Galaxie wählen"
    bl_description = "Alle Galaxien mit Bild: eine anklicken öffnet sie"

    def invoke(self, context, event):
        try:
            render_missing(context.scene)
        except OSError:
            pass
        window = context.window
        width = int(min(window.width * 0.8, 1100) / context.preferences.system.ui_scale)
        # A popup opens at the mouse: from the top middle of the window it hangs in the middle.
        # (MGE_NO_CURSOR_WARP=1: tests running beside the player's own work leave the mouse alone.)
        if os.environ.get("MGE_NO_CURSOR_WARP") != "1":
            window.cursor_warp(window.width // 2, int(window.height - 140 * context.preferences.system.ui_scale))
        return context.window_manager.invoke_popup(self, width=width)

    def execute(self, context):
        return {"FINISHED"}

    def draw(self, context):
        layout, scene = self.layout, context.scene
        wm = context.window_manager
        row = layout.row()
        row.label(text="Galaxie wählen", icon="WORLD")
        row.prop(wm, "mge_library_search", text="", icon="VIEWZOOM")
        try:
            groups = _groups(scene, wm.mge_library_search)
        except OSError:
            layout.label(text="Keine Spiel-Disc gefunden", icon="ERROR")
            return
        short = _short_names(scene)
        names = editor().galaxy_names(scene)
        current = scene.get("smg_galaxy")
        thumbs = editor().ui.thumbs()
        for title, galaxies in groups:
            if not galaxies:
                continue
            layout.separator()
            layout.label(text=title)
            grid = layout.grid_flow(row_major=True, columns=COLUMNS, even_columns=True, even_rows=True)
            for galaxy in galaxies:
                cell = grid.column(align=True)
                icon = thumbs.icon(f"Mini{galaxy}") or GLOBE
                cell.template_icon(icon_value=icon, scale=PICTURE)
                text = short.get(galaxy) or names.get(galaxy) or galaxy
                for tail in (" Galaxy", " Galaxie"):  # the word every name has: room for the rest
                    text = text[:-len(tail)] if text.endswith(tail) and len(text) > len(tail) else text
                op = cell.operator(MGE_OT_library_open.bl_idname, text=text, depress=galaxy == current)
                op.galaxy = galaxy


class MGE_OT_library_open(bpy.types.Operator):
    bl_idname = "mge.library_open"
    bl_label = "Galaxie öffnen"
    bl_options = {"INTERNAL"}
    galaxy: StringProperty()

    @classmethod
    def description(cls, context, properties):
        core = editor()
        name = core.galaxy_names(context.scene).get(properties.galaxy)
        mod = core.game_data(context.scene).registry().get(properties.galaxy, {}).get("mod")
        text = f"{name} ({properties.galaxy})" if name else properties.galaxy
        return text + (f" · Mod {mod}" if mod else "")

    def invoke(self, context, event):
        scene = context.scene
        scene.mge_galaxy = editor().galaxy_label(scene, self.galaxy)
        return bpy.ops.mge.open_galaxy("INVOKE_DEFAULT")


def open_soon(window):
    """The library over the 3D view of window, once it is drawn (the workspace opened without a galaxy;
    MGE_NO_LIBRARY_AUTO=1: not, for screenshot runs that open it themselves)."""
    if os.environ.get("MGE_NO_LIBRARY_AUTO") == "1":
        return

    def run():
        if window.scene.get("smg_galaxy"):
            return None
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                region = next((r for r in area.regions if r.type == "WINDOW"), None)
                with bpy.context.temp_override(window=window, screen=window.screen, area=area, region=region):
                    bpy.ops.mge.library("INVOKE_DEFAULT")
                return None
        return None
    bpy.app.timers.register(run, first_interval=0.6)


CLASSES = (MGE_OT_library, MGE_OT_library_open)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.mge_library_search = StringProperty(name="Suchen", options={"TEXTEDIT_UPDATE"},
                                                                description="Name im Spiel oder interner Name")


def unregister():
    del bpy.types.WindowManager.mge_library_search
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

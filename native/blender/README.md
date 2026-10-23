# MacioGalaxy Editor: galaxies in Blender

A Blender add-on (`macio_galaxy_editor/`) that opens a Super Mario Galaxy galaxy in the scene, edits it
with Blender's own tools, saves the changed zones as a MacioGalaxy mod, and plays them. It reads the
player's disc (`<user>/Disc/RMGE01`) with the enabled mods on top, as the game does; nothing of the
disc leaves the machine.

Objects, map parts, areas, gravity, start points and paths; objects and map parts drawn with the
game's models and textures (stand-in boxes for the rest: start points, logic objects).


## Install

```sh
ln -s "$PWD/native/blender/macio_galaxy_editor" ~/Library/Application\ Support/Blender/5.2/scripts/addons/
```

Then Blender → Preferences → Add-ons → "MacioGalaxy Editor" on. The add-on runs from the checkout, so
a pull updates it (restart Blender). In the 3D view: sidebar (N), the tabs **Galaxie** to **Spiel**.

## Use

The editor works in its own workspace **Galaxie** (a tab beside Layout, Modeling, ...). Opening a
galaxy switches to it (made the first time from a copy of Layout: the Properties editor, the timeline
and the Outliner closed, a space-blue viewport; `workspace.py`). A galaxy opens in a scene of its own,
"Mario Galaxy", when the current scene holds other things (the workspace starts in it, empty).

- **The sidebar (N), tab Galaxie**: a welcome checklist (disc found, object palette ready) and the
  galaxy to open, searched by its name in the game ("Good Egg Galaxy (EggStarGalaxy)"; the observatory is
  "Observatory Grounds (AstroGalaxy)") or its internal name. Once open: **Szenarien** (each with the main
  zone's layers it uses), **Zonen und Ebenen** (an eye and a solo button per zone; the selected zone's
  layers, ✓ = used by the scenario), **Spielen** (target mod and a switch to turn it on or off in
  `mods.txt`, **Speichern** = ⌘S in this workspace, **Automatisch testen (Bilder)** = the headless run
  with pictures, optionally from the Vorschau-Start, **Selbst spielen**), **Anzeigen** (the kinds drawn, with their colours as the legend;
  the sky and cameras start off), **Objektliste** (search, kind, zone; layer and ID per row).
- **Tab Objekt**: the selected object's picture, internal name, description, ID, a layer menu (for
  every selected object), **Lage im Spiel** (position, rotation, scale in game units, editable), and its
  fields: **Argumente** with their meaning and a menu of the values the object database lists (unused
  ones folded away), **Schalter**, **Verknüpfungen** (MessageId shows the message's text, CommonPath_ID
  has a path chooser), **Weitere Felder**; at the bottom Speichern, Testen and Spielen.
- **The object palette**: a strip at the bottom of the 3D view (an asset shelf, `shelf.py`) with every
  placeable object, level part and gravity as a picture, in German catalogs (Objekte/Gegenstände,
  Gegner, Levelteile, ..., Schwerkraft; an older palette is rebuilt in the background). A click chooses it for the Setzen tool and
  switches to it; dragging it onto a planet places it there. The full catalog (areas, cameras, ...) is
  the asset library "Mario Galaxy" in the Asset Browser and the Setzen tool's search (German names
  like "Münze", "Gumba" work too).
- **The toolbar** (left, `tools.py`, with their own icons): **Setzen** (a click on a surface places the
  chosen object standing on it, at the chosen height, in the clicked object's zone and layer; a click
  on a small placed object selects it, Ctrl/⌘+click places anyway; nothing is placed into empty space;
  a layer the scenario does not use is warned about), **Pfad zeichnen** (points on surfaces, straight
  unless "Kurven"; Enter or right click ends; the path has its ID at once; then a menu offers a coin line
  or purple coin line along it, RailCoin with CommonPath_ID and a coin count for its length), **Schwerkraft** (a click on a planet: the gravity at the middle of its bounds with a
  fitting Range), **Vorschau-Start** (where Mario starts in the automatic test).
- **The HUD** (`hud.py`): the galaxy and scenario, where new things go, what the active tool does, the
  selection's keys, "● ungespeichert" while there are unsaved changes (also after deleting), and the
  colour legend above the palette; without a galaxy a card says what to do.
- **Q** opens a pie menu with the tools, automatic test, saving, playing and "back to the start"
  (in this workspace; elsewhere Blender's Quick Favorites). **Zum Start** frames Mario's start.
- Move, rotate, scale, duplicate (Shift+D) and delete as usual; a duplicated path gets its own ID, and a
  path's point_arg values stay with their points when points are added or removed. A path of several
  parts (Shift+D in edit mode) is refused on saving: P separates the parts into paths. Saving is an
  undo step. Opening another galaxy with unsaved changes asks first.
- **Objekt-Palette aufbauen** / **Vorschaubilder erzeugen** (menu Galaxie in the top bar) rebuild the
  palette and the pictures (models are rendered in a second, headless Blender at low priority, waiting
  while the game runs; areas, cameras and gravity are drawn as wire pictures without Blender).

## Models

- An object's model is `ObjectData/<Name>.arc` (the winning enabled mod's, else the disc's), or the
  archive Whitehole's `modelsubstitutions.json` names (`BenefitItemOneUp` → `KinokoOneUp`, ...);
  observatory pieces add their dome by Obj_arg0 (`AstroDomeEntrance` 2 → `AstroDomeEntranceWell`,
  as `AstroMapObjFunction::getModelName`);
  inside, `<name>.bdl`/`.bmd`. `native/tools/j3d_scene.py` poses it at rest: JNT1 joints through the
  INF1 tree (`parent · T · Rz · Ry · Rx · S`), rigid DRW1 matrices applied, skinned (EVP1) vertices
  left in model space; display lists decoded with numpy. `native/tools/gx_texture.py` decodes every
  GX texture format.
- Converted once into `~/Library/Caches/MacioGalaxyEditor` (`models/<hash>.npz`, `textures/<hash>.png`);
  every object of a name shares one mesh. Every galaxy opens with its models (none fails); Good Egg
  (104 models) in about 6 s once cached. Objects without a model (lights, effects, demo starters)
  stay stand-ins.
- Materials approximate the game's TEV: the texture stage 0 samples (wrap modes, UV set) times vertex
  colours or the material colour, alpha clip/blend, backface culling. An environment map (the coin,
  the stars) becomes its mean colour. Colours the game sets at run time stay grey (the Lumas' body).
  Animated characters stand in their rest pose.

## How it maps

- Game space is Y up in game units; Blender is Z up, 1 m = 100 units: (x, y, z) → (x, −z, y) / 100.
  An object is `T(pos) · Rz(dir_z) · Ry(dir_y) · Rx(dir_x) · S(scale)` (degrees); in Blender the
  same rotation in Blender's axes, with scale (sx, sz, sy). Objects use quaternion rotation: Blender's
  Euler angles hit gimbal lock for some of the game's rotations.
- Each object keeps the row it came from and its matrix as read. Saving rebuilds the zone's tables from
  the scene: an unchanged object keeps its row's bytes exactly, a moved one gets new pos/dir/scale, a
  duplicate or a new object a new row with an `l_id` no other object or map part of the zone has.
  Unmoved path points keep their exact values (Blender stores coordinates as 32-bit metres).
- Archives are rebuilt with `native/tools/rarc_tree.py` (folders, new and removed files: a new path's
  point table) and written as plain RARC, which the game reads as well as Yaz0.

## Limits

- Materials are approximations (see Models); sphere, cylinder and bowl areas use scale_x for their radius in the
  game, while Blender stretches them with every axis.
- Not editable yet: camera parameters (`cameraparam.bcam`), scenarios and their layers, new zones or
  galaxies, the galaxy's place in the observatory.
- One galaxy in the scene at a time.

## Tests

```sh
B=/Applications/Blender.app/Contents/MacOS/Blender
$B --background --factory-startup --python native/blender/tests/editor_test.py -- WORK_DIR [GALAXY]
$B --background --factory-startup --python native/blender/tests/play_test.py -- WORK_DIR [GALAXY]
```

Both work in `WORK_DIR` on a throwaway user folder (the disc linked, the mods copied). `editor_test`
saves without a change (nothing may be written), then moves, adds, duplicates and deletes objects,
adds gravity and a path, and reads the saved archive back. `play_test` places five coins and a box in
front of Mario's start and plays the galaxy headless (not while the game runs). Every galaxy of the disc
and the mods opens and saves back unchanged (all 236 zones of 50 galaxies).

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
galaxy switches to it (made the first time from a copy of Layout: the Properties editor and the
timeline closed, the Outliner kept, a space-blue viewport; `workspace.py`; a workspace of an older
layout is made again). A galaxy opens in a scene of its own, "Mario Galaxy", when the current scene
holds other things (the workspace starts in it, empty).

- **The galaxy library** (`library.py`): a window in the middle of the screen with every galaxy as a
  picture (its dome miniature, rendered once in the background), grouped: the mods' galaxies, the
  galaxies, the rest (hubs, small galaxies); a search field narrows them by either name. A click opens
  the galaxy. It opens by itself when the workspace starts without a galaxy, and from the header.
- **The 3D view's header**: the galaxy (a click: the library) and its mission.
- **The tool header**: Speichern (red while there are unsaved changes; ⌘S in this workspace),
  **Testspielen** (the level testbed, below; ✕ stops it) and a switch per kind drawn, a swatch in its
  colour (the name in its tooltip): objects, level parts, areas, cameras, gravity, starts, paths, zones,
  sky, the rest. Areas, cameras, gravity and paths are drawn over Blender's one-pixel wires in these
  colours (`outlines.py`).
- **The sidebar (N), tab Galaxie**: Galaxie wählen, Modelle on/off, Zum Start; **Zonen und Ebenen** (an eye
  and a solo button per zone; the selected zone's layers, ✓ = used by the scenario); **Mod und Tests**
  (closed: the target mod and its switch in `mods.txt`, the Teststart, the testbed's window, the
  automatic test with pictures, the whole game with `--stage`, the line width).
- **Tab Item, panel Galaxie-Objekt** (below Blender's Transform): the selected object's picture, name,
  kind and ID, a zone menu and a layer menu (both for every selected object; another zone keeps the
  objects where they stand in the galaxy and makes them new rows there, paths with a free ID), its
  internal name; **Lage im Spiel** (closed: position, rotation, scale in game units; the rotation shows
  the zone's own dir values while the object is turned as read, and typing one angle keeps the other
  two), **Punkte** for a path (a point number, marked in the viewport, and its point_arg0..7), and its
  fields: **Argumente** ("Color Frame · arg1", with a menu of the values the object database lists;
  unused ones folded away), **Schalter**, **Verknüpfungen** (MessageId with its text, CommonPath_ID
  with a path chooser), **Weitere Felder**. With several objects selected, ↓ beside a field copies its
  value to all selected that have it (arguments only to objects of the same name), and "gemischt"
  marks a field whose values differ; the value menus and the path chooser set all of them.
- **The Outliner**: Blender's, with the galaxy's collections (zones, their layers and paths) and objects.
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
  fitting Range), **Teststart** (where Mario starts in Testspielen and the automatic test, with "Am
  Teststart beginnen" on; the galaxy's own start stays).
- **In the view** (`hud.py`): only markers, the path point being edited and the Teststart ring.
- **Q** opens a pie menu with the tools, automatic test, saving, Testspielen (and the whole game below
  it) and "back to the start" (in this workspace; elsewhere Blender's Quick Favorites). **Zum Start** frames Mario's start.
- Move, rotate, scale, duplicate (Shift+D) and delete as usual; a duplicated path gets its own ID, and a
  path's point_arg values stay with their points when points are added or removed. A path of several
  parts (Shift+D in edit mode) is refused on saving: P separates the parts into paths. Saving is an
  undo step. Saving warns about galaxy objects moved out of the galaxy's collection (they are not
  saved). Opening another galaxy with unsaved changes asks first.
- **Objekt-Palette aufbauen** / **Vorschaubilder erzeugen** (menu Galaxie in the top bar) rebuild the
  palette and the pictures (models are rendered in a second, headless Blender at low priority, waiting
  while the game runs; areas, cameras and gravity are drawn as wire pictures without Blender).

## Testspielen: the level testbed

**Testspielen** (F5 in the 3D view, the big button on top of the Spielen panel, the Q pie, the menu
Spiel) saves and plays the galaxy in **Galaxy Testbed** (`native/app/testbed_main.cpp`, built as
`build/macos-gx/native/app/Galaxy Testbed.app`; `/Applications/Galaxy Testbed.app` is used first if it is
there, `MGE_TESTBED` names another). It is the game's own code for one galaxy: scene, objects,
collision, gravity, camera, Mario and the controls (`controls.txt`) in a window of its own, without the
Wii strap screen, title, file select or observatory.

How to use it:

1. Testspielen: the window "Galaxy Testbed – <galaxy>, Mission <n>" opens; about 10 s later Mario can
   be played (the Spielen panel and the status bar count the seconds).
2. Edit in Blender, then ⌘S (or F5; also without a change, to start the mission again): the running
   testbed loads the changes and starts the mission again in about 8 s, and comes to the front. The
   panel shows "Testspiel läuft" with **Fenster** (to the front) and **Beenden**; ⌘Q in its window
   closes it too. While it starts, the button waits ("Testspiel startet …"), so it never runs twice.
3. Another mission (the Szenarien list) or a reload that cannot be done in place starts a fresh
   testbed instead. "Im ganzen Spiel spielen" closes a running testbed first.

- **Start**: straight from the save mount to the galaxy and mission (`--stage`, `--scenario`), through
  the game's after-loading galaxy move (`GameSequenceProgress::endScene`, `petari/testbed.hpp`). The
  file is a new one held in memory only: the story through, galaxies open, opening demos seen and
  missions visited, but no Power Star anywhere, so the counter starts at 0 and every star is still to
  be won (`NativeUnlockedSave::prepareTestbedFile`); nothing of the player's save is read. The mission's opening camera flight is skipped as the
  player could with A (`--opening` keeps it); Mario's own entrance stays (Good Egg 1: the flight in,
  then the game's "Welcome to the Galaxy!").
- **Never to the title**: a game over (no "save?" prompt), a star, leaving the galaxy from the pause
  menu or a reset start the tested mission again on a fresh file (`GameSequenceProgress::requestGalaxyMove`).
- **Folders**: its own `~/Library/Caches/MacioGalaxyEditor/testbed/user` (crash reports; anything the
  game writes there is wiped at the next start); from the player's folder it only reads the settings
  (controls, camera, cheats, sound, graphics, `mods.txt`) and links `mods/`. The shader cache is the
  game's (`~/Library/Caches/Petari`) unless the game holds it. Refused while the player's game runs.
  Zone archives are written whole (a temporary file renamed into place), so the testbed never reads
  half a file.
- **Reload**: Testspielen or ⌘S sends `reload` over the testbed's socket
  (`~/Library/Caches/MacioGalaxyEditor/testbed/control.sock`). At the next frame of normal play (in the
  tested galaxy or another one after the F1 Level Select; it waits while the pause menu, a demo or a
  death is on) the testbed restarts the mission through the Level Select's warp. That scene change
  drops the file cache the game keeps for a same-stage restart and, with the old scene gone, rebuilds
  the disc's mod overlay (`DVD::refreshOverlay`, the player's `mods.txt` read again): rewritten zone
  archives with their new sizes. A change that adds, removes or renames files (a new mod, a new galaxy)
  would change entry numbers the game keeps from start-up: the testbed refuses it, and Blender starts a
  fresh one. A save while a reload is under way is picked up by another restart. A mission that cannot
  be reached gives up after 3 restarts (an error in `status`, and Blender starts afresh).
- **Teststart**: with "Mario startet am 3D-Cursor (Teststart)" on (a ring "Mario-Start (Test)" marks
  the cursor in the viewport), Mario is put at the 3D cursor once the mission is playable: after every
  start, reload, game over or star (`--spawn x,y,z` or `name:<GeneralPos>`); not after a miss (the
  game's own checkpoint).
- **Socket commands** (one line each): `reload [x,y,z|name:POS|none]`, `spawn ...` (from the next
  restart), `status` (stage, mission, playable now, reloads, seconds to control after launch and after
  the last reload, pid, the last reload error), `quit`; for tests: `where` (Mario's position and
  state), `press <button> [frames]` (through the player's bindings), `lives <n>`, `warp <stage>
  <mission>` (as the Level Select), `actors` (with `PETARI_OBSERVE=1`). `PETARI_TESTBED_TRACE=1` logs
  what holds Mario while a mission starts; `PETARI_SURFACE_DUMP_LABELS=testbed` takes pictures from the
  moment of control.

Measured on Good Egg 1 (M3 Pro, the same warm shader cache, hidden window), launch to the first frame
Mario can be moved:

| | Launch to control | After a save |
| --- | --- | --- |
| Testbed | 8.7 s (10.2 to 10.5 s the first launch after a build) | 7.8 s in-process |
| Whole game, `--stage` ("Im ganzen Spiel") | 28.3 s with title and file select pressed through at once (the stage smoke) | a relaunch: 28.3 s again, plus quitting and the player's own clicks |

Where the testbed's time goes: about 2 s to the loaded galaxy (1.8 s on a reload), then the start
wipe and Mario's flight in (about 5.5 s in Good Egg 1, the mission's own start). The whole game
spends 11 s before the galaxy (title and file select with instant presses) and 15 s from the loaded
galaxy to control (opening camera flight, flight in).

Tested hidden (`--background`) on Good Egg 1 and 3, Honeyhive, Battlerock, Freezeflame, Boo's
Boneyard (2D), Gateway and two mod galaxies (GuglisPlanet, ExampleGalaxy): launch, reload, input
(walking, jumping, spinning through the player's bindings), the Teststart, a reload while paused, from
another galaxy, during the launch and twice in a row, a game over, 30 reloads in a row, a second
testbed refused, quitting.

Not yet: overlays for gravity fields, areas and collision, a free camera, respawn at the cursor;
custom geometry from Blender (a mesh as display model with generated collision) loaded directly;
shortening Mario's entrance flight (about 5.5 s of every Good Egg start).

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
$B --background --factory-startup --python native/blender/tests/testbed_test.py -- WORK_DIR [GALAXY]
```

All work in `WORK_DIR` on a throwaway user folder (the disc linked, the mods copied). `editor_test`
saves without a change (nothing may be written), then moves, adds, duplicates and deletes objects,
adds gravity and a path, and reads the saved archive back; last, Testspielen against a stand-in
testbed (reload with the spawn, another galaxy restarts it). `play_test` places five coins and a box in
front of Mario's start and plays the galaxy headless (not while the game runs). `testbed_test` starts
the testbed hidden on an edit, adds a Goomba, saves, and checks that the reload in the same process
brings it into the game, then a reload with a spawn point (not while the game runs). With
`MGE_TESTBED_BACKGROUND=1` Testspielen starts the testbed hidden (for testing the editor's own UI). Every galaxy of the disc
and the mods opens and saves back unchanged (all 236 zones of 50 galaxies).

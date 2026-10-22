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

The editor's own tabs in the 3D view's sidebar (N): **Galaxie**, **Objekte**, **Eigenschaften**,
**Spiel**.

- **Galaxie**: pick a galaxy in the search field, by its name in the game ("Good Egg Galaxy
  (EggStarGalaxy)"; the observatory is "Observatory Grounds (AstroGalaxy)") or its internal name, and
  open it (the folder button). One galaxy at a time. **Szenarien** lists the scenarios by their names
  in the game; choosing one shows the zones and layers it uses. **Zonen und Ebenen**: every zone with
  an eye, and the selected zone's layers with an eye each (✓: used by the scenario); "Alles zeigen" or
  back to the scenario's. **Anzeigen** switches what is drawn: objects, map parts, areas, cameras,
  gravity, start points, paths, zone placements, other (sounds, positions, demos).
  **Modelle des Spiels** (on) draws objects with their models, off as coloured stand-ins.
- **Objekte**: **In der Galaxie** lists every placed object (its name in the game, its zone and
  layer), filtered by kind and zone and searchable; a click selects it, **Zeigen** frames it. **Neues
  Objekt** is the game's catalog with preview pictures, by kind or by the object database's category
  (Enemies, Planets, ...): choose one and **Am 3D-Cursor einfügen** places it in the active layer (the
  Outliner's active layer collection, else the selected object's). **Path hinzufügen** adds a two-point
  path. **Vorschaubilder erzeugen** renders the pictures once in a second, headless Blender
  (`thumbnails.py`; about two minutes for all, waiting while the game runs).
- **Eigenschaften**: the selected object's picture, name in the game, description, layer (a menu
  moves it to another layer), **Lage im Spiel** (position, rotation in degrees, scale in game units in
  its zone, editable), **Argumente** with their meaning from the object database (unused ones folded
  away; gravity also shows Range, Distant, ...), **Schalter**, **Verknüpfungen** (path, camera,
  message, group ids) and **Weitere Felder**.
- Move, rotate, scale, duplicate (Shift+D) and delete as usual in the viewport. To move an object to
  another layer, use the layer menu or move it to that layer's collection.
- **Spiel**: **Als Mod speichern** writes the changed zones to `<user>/mods/<Mod>/files/StageData`
  (`Mod`: by default the mod the galaxy came from, else `BlenderEdits`), switches the mod on in
  `mods.txt` and raises its priority above any enabled mod with the same files. **Vorschau
  (unsichtbar)** saves, plays the galaxy headless in a throwaway save (with the cursor button: Mario
  starts at the 3D cursor) and opens the pictures in Preview; it refuses while the game runs (two
  games on one GPU have crashed the running one). **Im Spiel starten** saves and starts the game: after
  you load a file it goes straight to the galaxy.
- The scene: a collection `SMG <Galaxy>`, one per zone, one per layer and `<Zone> Paths`. The main zone
  places the other zones; each placement is a `Zone <Name>` object whose children are the zone's
  contents: move it and the zone moves.

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

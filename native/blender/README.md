# MacioGalaxy Editor: galaxies in Blender

A Blender add-on (`macio_galaxy_editor/`) that opens a Super Mario Galaxy galaxy in the scene, edits it
with Blender's own tools, saves the changed zones as a MacioGalaxy mod, and plays them. It reads the
player's disc (`<user>/Disc/RMGE01`) with the enabled mods on top, as the game does; nothing of the
disc leaves the machine.

Stage 1: objects, map parts, areas, gravity, start points and paths. Objects are stand-ins (coloured
boxes with a nose toward their front), not the game's models yet.

## Install

```sh
ln -s "$PWD/native/blender/macio_galaxy_editor" ~/Library/Application\ Support/Blender/5.2/scripts/addons/
```

Then Blender → Preferences → Add-ons → "MacioGalaxy Editor" on. The add-on runs from the checkout, so
a pull updates it (restart Blender). In the 3D view: sidebar (N), tab **Galaxy**.

## Use

- **Galaxie öffnen**: pick a galaxy (search field), open it. One galaxy at a time; opening another
  replaces it. **Szenario** shows the layers that scenario uses and hides the others (they stay in
  the scene and are saved).
- The scene: a collection `SMG <Galaxy>`, one per zone, one per layer (`<Zone> common`, `<Zone>
  layera`, ...) and `<Zone> Paths`. The main zone places the other zones; each placement is a
  `Zone <Name>` object, and the zone's contents are its children: move it and the zone moves.
- Move, rotate, scale, duplicate (Shift+D) and delete as usual. **Auswahl** lists the object's fields
  (name, l_id, Obj_arg0..7, switches, ...) with what they mean, from Whitehole's object database when it
  is there (`../Whitehole/src/dist/data/objectdb.json`). To move an object to another layer, move it to
  that layer's collection.
- **Objekt / Gravity / Area / Alle Arten**: search the game's objects (by how often the game uses them)
  and place one at the 3D cursor in the active layer collection (Outliner), with the values of its
  first placement on the disc, so it starts out working. **Path hinzufügen**: a two-point path; edit
  its points in Edit Mode (Tab); the handles are the game's control points.
- Gravity draws its range (Range, Distant, scale, Obj_arg) and redraws when you change them. Areas
  draw their shape (box from the bottom, centred box, sphere, cylinder, bowl).
- **Spiel**: **Als Mod speichern** writes the changed zones to `<user>/mods/<Mod>/files/StageData`
  (`Mod`: by default the mod the galaxy came from, else `BlenderEdits`), switches the mod on in
  `mods.txt` and raises its priority above any enabled mod with the same files. **Vorschau
  (unsichtbar)** saves, plays the galaxy headless in a throwaway save (with the cursor button: Mario
  starts at the 3D cursor) and opens the pictures in Preview; it refuses while the game runs (two
  games on one GPU have crashed the running one). **Im Spiel starten** saves and starts the game: after
  you load a file it goes straight to the galaxy.

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

## Limits (stage 1)

- Stand-ins instead of models; sphere, cylinder and bowl areas use scale_x for their radius in the
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

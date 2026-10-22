# Custom galaxies

A disc-file mod (native/MODS.md, "Mod folder") can add a whole galaxy: its level, a
miniature in a Comet Observatory dome, its names and dialogue, and objects with new
logic. This page shows how with an example, "Guglis Testgalaxie", and what the port
does so that such a mod never touches the game's own save.

## The example

```sh
python3 native/tools/make_example_galaxy.py
```

builds `mods/ExampleGalaxy` in the user directory from your own disc (the disc is
only read; the mod holds files derived from it, so it stays on your machine). Turn
it on in F1 → Mods → Mod folder (or `PETARI_MOD_FOLDERS=ExampleGalaxy` for one run)
and start the game again. Then:

- **In the Terrace (the first dome)** a sixth miniature circles outside Good Egg,
  Honeyhive, Loopdeeloop and Flipswitch, inside Bowser Jr.'s Robot Reactor:
  "Guglis Testgalaxie", open from the start.
- **Its level** is Sweet Sweet Galaxy's under the new name, with one mission, "Die
  tanzenden Kisten".
- **A new Toad** at the start explains the galaxy, over several pages; Sweet Sweet's
  own Toads have new lines too.
- **Three new objects**, `GuglisSpinBox` (`src/Game/MapObj/GuglisSpinBox.cpp`): boxes
  that float, turn and bob. A spin attack gets a coin and makes a box swell; after
  5, 3 or 1 spins (Obj_arg0) it bursts into eight coins.

The mod's files:

| File | What it is |
| --- | --- |
| `files/StageData/ExampleGalaxy.arc` | the level: placement, collision, cameras (Sweet Sweet's, plus the Toad and the boxes) |
| `files/StageData/ExampleGalaxy/ExampleGalaxyScenario.arc` | its scenario and zone lists; the game finds galaxies by this file alone |
| `files/ObjectData/MiniExampleGalaxy.arc` | the dome miniature's model (Good Egg's, renamed) |
| `files/StageData/AstroDome.arc` | the domes, with a `MiniExampleGalaxy` placed in dome 1 (layer A) |
| `messages.txt` | names and dialogue |
| `mod.txt` | name, description, and the galaxy's sounds |

## Building your own

- **The level:** any level editor for Super Mario Galaxy writes these archives, e.g.
  Whitehole Neo (its "SMG1 1 Star Galaxy" template), with models from Blender through
  SuperBMD and collision from pyKCLCreate. `native/tools/stage_edit.py` changes
  placement tables from the command line.
- **The galaxy's name** is the scenario archive's: `StageData/<Galaxy>/<Galaxy>Scenario.arc`
  (with `ScenarioData.bcsv` and `ZoneList.bcsv`) and `StageData/<Galaxy>.arc`. At
  most 64 galaxies (the game has 48), at most 7 stars each.
- **Its dome:** place an object `Mini<Galaxy>` (Obj_arg0 0) in `AstroDome.arc`'s layer
  of the dome (layer A is the Terrace, B the Fountain and so on) and supply
  `ObjectData/Mini<Galaxy>.arc`. The port makes every `Mini<Galaxy>` of a mod's galaxy
  a dome miniature; the mod's galaxies orbit outside the dome's own (up to eight orbits).
- **Text:** `messages.txt`, one `ID = text` per line, `#` for comments. Every enabled
  mod's file is read, the first line for an ID wins, and a disc message with the
  same ID wins over all of them. `messages.<Language>.txt` (e.g. `messages.UsFrench.txt`)
  goes before `messages.txt` for that language. In the text: `\n` a new line (a
  balloon shows three), `[page]` the next page, `[wait N]` N frames, `[color N]` a
  colour (0 back to normal), `[player]` the player's name.
  - `GalaxyName_<Galaxy>`, `GalaxyNameShort_<Galaxy>`, `ScenarioName_<Galaxy><N>`: the
    names. Missing, the galaxy is called "???".
  - NPC lines: `<Zone>_<Actor><MessageId, three digits>`, e.g. `ExampleGalaxy_Kinopio005`
    for a Toad (Kinopio) with MessageId 5 in the zone ExampleGalaxy. Every NPC needs its
    line: without one its balloon has no text, which is likely to crash when Mario talks
    to it.
- **Sounds and music:** `<Galaxy>.sound=<original galaxy>` in `mod.txt` uses that
  galaxy's sound effects and music (Sweet Sweet Galaxy's without the line).
- **New logic:** a C++ class in `src/Game/...` and a row in the `NameObjFactory.cpp`
  table, as `GuglisSpinBox`; place it by name like any object. That part is code in
  the port, not in the mod.

## The game's save stays the game's

Turning a mod on, playing it, turning it off or deleting it never changes the game's
own progress:

- **The save file:** a mod's galaxies are never written to `GameData.bin`. Their
  stars, best coin counts and "visited" marks go to `ModProgress/<slot>.txt` in the
  user directory (`mario1.txt`, `luigi1.txt` …), written when the game saves your
  file, read when it loads it, cleared when a file is created or deleted and copied
  with it. `GameData.bin` stays exactly what the game alone would write, so it also
  works in Dolphin, Nebula or on a Wii (`native/tools/convert_save.py`).
- **The star count:** a mod's stars do not count for the game's own goals (domes,
  Grand Stars, the 120-star ending) or its star total.
- **Unlocking:** a mod's galaxy has no flag in the game's flag table: it is open from
  the start, and nothing about it is saved.
- **Off again:** without the mod its galaxy, miniature and texts are simply gone; its
  progress waits in `ModProgress/` for when it is turned on again.

What a mod still shares with the game: lives, coins and Star Bits collected in its
galaxy count as in any other. A mod that changes one of the game's own levels (not
a new galaxy) changes that level, and its stars count as the game's.

## How the port does it

- `native/app/platform_host.cpp`: which galaxies mods add (their scenario archive is
  a mod's and not on the disc), their progress files, the mods' `messages.txt` and
  `mod.txt` sound lines. The game code reaches them through the hooks in
  `native/include/petari/mod_galaxies.hpp`, which stay empty without the app.
- `MessageHolder.cpp`: messages not on the disc come from the mods' text.
- `GameDataGalaxyStorage.cpp`, `SaveDataHandler.cpp`, `GameDataFunction.cpp`: mod
  galaxies kept out of the file and the star totals, their progress per slot.
- `GameEventFlagChecker.cpp`, `GameDataConst.cpp`, `GameEventFlagTable.cpp`: a galaxy
  without a flag or a `GalaxyID` row is open and needs no stars, instead of crashing.
- `NameObjFactory.cpp`, `MiniatureGalaxyHolder.cpp`, `MiniatureGalaxy.cpp`,
  `AstroDomeOrbit.cpp`: `Mini<Galaxy>` miniatures, six to eight orbits in a dome.
- `AudSceneMgr.cpp`, `AudStageBgmWrap.cpp`: the borrowed sounds and music.
- `MessageUtil.cpp`: "???" for a galaxy name no file supplies.

Testing a mod's galaxy without the observatory: `--test-fixture stage` with
`PETARI_STAGE=<Galaxy>` accepts a galaxy that a mod in the user directory adds.

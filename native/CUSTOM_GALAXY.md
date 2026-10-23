# Custom galaxies

A disc-file mod (native/MODS.md, "Mod folder") can add a whole galaxy: its level, a
miniature in a Comet Observatory dome, its names and dialogue, and objects with new
logic. The galaxy itself is registered the official way, with a `galaxy.json`
(docs/dev/level-editor/new-galaxies.md: names, missions, borrowed music, its own save
beside `GameData.bin`, and the "Mod galaxies" section of Level Select); this page adds
what that registry does not have: the dome miniature, dialogue, new objects, a planet
from Blender and the theme colour. It shows how with an example, "Guglis Testgalaxie". "Your own planet" builds
a galaxy from a planet modelled in Blender; "The observatory" adds a sky island to the
Comet Observatory; "The theme colour" is the mods' hazelnut brown.

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
| `files/StageData/ExampleGalaxy/ExampleGalaxyScenario.arc` | its scenario and zone lists |
| `galaxy.json` | the registry entry: the galaxy's name, short name and mission name, and the music it borrows (Sweet Sweet Galaxy's); without it the game skips the galaxy |
| `files/ObjectData/MiniExampleGalaxy.arc` | the dome miniature's model (Good Egg's, renamed) |
| `files/StageData/AstroDome.arc` | the domes, with a `MiniExampleGalaxy` placed in dome 1 (layer A) |
| `messages.txt` | dialogue |
| `mod.txt` | the mod's name and description |

## Building your own

- **The level:** any level editor for Super Mario Galaxy writes these archives, e.g.
  Whitehole Neo (its "SMG1 1 Star Galaxy" template), with models from Blender through
  SuperBMD and collision from pyKCLCreate. Without them, the tools here do it in Python
  (see "Your own planet"): `native/tools/stage_edit.py` changes placement tables,
  `j3d_mesh.py` writes a model, `kcl_write.py` its collision, `rarc_write.py` an
  object archive.
- **The galaxy's name** is the scenario archive's: `StageData/<Galaxy>/<Galaxy>Scenario.arc`
  (with `ScenarioData.bcsv` and `ZoneList.bcsv`) and `StageData/<Galaxy>.arc`, at most 40
  characters of `[A-Za-z0-9_]`. At most 64 galaxies (the game has 48), at most 8 missions
  and 7 stars each.
- **Its registry entry** (required): `galaxy.json` beside `files/`, as in
  docs/dev/level-editor/new-galaxies.md 5: `{"format": 1, "galaxies": [{"name": "<Galaxy>",
  "title": {"en": ...}, "shortTitle": {"en": ...}, "missions": [{"en": ...}], "music":
  "<disc galaxy>"}]}`. The names are the galaxy's in the observatory, Level Select and the
  pause menu ("en" is the fallback for every language); `music` is the disc galaxy whose
  music and sound banks it borrows. A galaxy without an entry is skipped.
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
  - The galaxy's names are `galaxy.json`'s, not `messages.txt`'s.
  - NPC lines: `<Zone>_<Actor><MessageId, three digits>`, e.g. `ExampleGalaxy_Kinopio005`
    for a Toad (Kinopio) with MessageId 5 in the zone ExampleGalaxy. Every NPC needs its
    line: without one its balloon has no text, which is likely to crash when Mario talks
    to it.
- **New logic:** a C++ class in `src/Game/...` and a row in the `NameObjFactory.cpp`
  table, as `GuglisSpinBox`; place it by name like any object. That part is code in
  the port, not in the mod.

## Your own planet

```sh
python3 native/mods/GuglisPlanet/build.py
```

builds `mods/GuglisPlanet`, "Guglis Testplanet": a small planet modelled in Blender, in
the Terrace next to the other miniatures. It needs Blender (`/Applications/Blender.app`,
run in the background) and your disc, nothing downloaded.

- **The planet** is made by `native/mods/GuglisPlanet/planet_blender.py` and kept as
  `ModSources/GuglisPlanet/GuglisTestPlanet.blend` in the user directory: a hilly ball
  of grass with a winding soil path (the sphere is cut along the path's edge, so the
  edge follows its curve) and four cut-stone pillars, 24 m across (1 m in
  Blender is 100 units in the game; Mario is 1.6 m). Edit it there and run
  `build.py --from-blend`. The rules: meshes in the collection "Planet", material slots
  named after the template's materials (`Green_v`, `Ground_v`, `CutStone_v`, Stardust
  Hill's), shading in the colour attribute "Col"; empties in "Markers" give Mario's
  start, the spin boxes and the star.
- **Model and collision:** `native/tools/j3d_mesh.py` writes the mesh into Stardust
  Hill's planet model (its materials and textures stay, so it looks like the game),
  with box-mapped texture coordinates at the texture's own density; `kcl_write.py`
  builds the collision with grass, soil and stone footsteps; `rarc_write.py` packs
  `ObjectData/GuglisPlanetSphere.arc`. The miniature is the same mesh, smaller.
- **The stage** is Snow Cap Galaxy's (one small planet, aurora sky), emptied and
  rebuilt around the planet: the game's small-planet camera, a new opening flight
  round the planet (`camera/StartScenario1.canm`, `canm.py`), then the Launch Star
  rail brings Mario down on the north pole.
- **The challenge:** three `GuglisSpinBox` objects (3 spins each). Each turns a switch
  on when it bursts (SW_DEAD); the game's `GroupSwitchWatcher` turns switch 20 on once
  all three have; `GuglisStarAppear` (`src/Game/MapObj/GuglisStarAppear.cpp`) then
  brings the scenario's star out above the tallest pillar, seen by its own camera
  (`e:パワースター固有001`), and it flies down beside the pillar.
- **The star** is in the theme colour, like every star of a mod's galaxy (below).
- **A placed object a mod brings** (`ObjectData/<Name>.arc` not on the disc, no class
  of its own) is a planet: a model and, when the archive has one, its collision.

Only one mod's `StageData/AstroDome.arc` is used, the highest priority's
(native/MODS.md). The planet's `mod.txt` has priority 1, and `build.py` puts the
miniatures of other mods' galaxies it finds in the user directory into its dome as
well (a miniature whose mod is off is left out).

## The theme colour

The mods' own things are hazelnut brown (#8A5A32). `native/mods/theme.py` makes the
files from the disc, and the mods' build scripts (and Whitehole's `game_export_mod`)
put them into the mod; each uses a slot the game leaves unused, so the original look
stays:

- **Stars of mods' galaxies:** the star model's unused colour slot gets a hazelnut
  texture (`ObjectData/PowerStar.arc`), with a hazelnut light, also on the star's way
  back to the observatory.
- **Their counter:** under the game's star counter, shown and hidden with it
  (`src/Game/Screen/ModStarCounter.cpp`; its layout is the star counter's with a
  hazelnut icon, `LayoutData/GuglisStars.arc`). It counts the file's stars of mods'
  galaxies, apart from the game's stars (see below).
- **Launch Stars:** place one as `SuperSpinDriverHazel`. The Launch Star model's spare
  texture slot gets its own hazelnut image and BTP frame 3 shows it, with the yellow
  star's shimmer (`hazel.brk`) and a hazelnut flight path (`hazel.bti` in
  `ObjectData/SpinDriverPath.arc`). Without the theme's files it is yellow.

## The observatory

`native/mods/Sternenschiff` adds a sky island east of the Luma garden: a grassy island on
a rock (modelled in Blender, `island_blender.py`, written by `build.py` as
`ObjectData/GuglisSkyIsland.arc` with its collision), a Toad with his own lines, a ring of
Star Bits, butterflies, and two hazelnut Launch Stars: one in the garden to the island, one
on the island back. The observatory itself (`StageData/AstroGalaxy.arc`) was edited in
Whitehole through its MCP tools (Whitehole fork, `mac/README.md`) and exported with
`game_export_mod`; new things go on the common layer, which every state of the
observatory shows.

- The Toad's line: `AstroGalaxy_Kinopio200` in the mod's `messages.txt` (a Toad with
  MessageId 200 in the zone AstroGalaxy). A new NPC needs a MessageId the disc does not
  use in its zone: a disc message wins over the mods' (the observatory's Toads use 000-100),
  and with it comes its talk flow. MessageId 90, the Toad with Peach's letter, ends by
  handing out a star, and the island has none to give: the game crashed.
- No Power Stars or coins in the observatory, as on the disc: collectibles there are
  Star Bits.
- A Launch Star takes Mario only once he has been over 350 units from it: start the
  smoke run's `launchstar` check (below) from there.
- The mod replaces `StageData/AstroGalaxy.arc` as a whole, so two mods changing the
  observatory conflict (the higher priority's wins).

## The game's save stays the game's

Turning a mod on, playing it, turning it off or deleting it never changes the game's
own progress. The registry does most of it (docs/dev/level-editor/new-galaxies.md 2):

- **The save file:** a mod's galaxies are never written to `GameData.bin`. Their stars,
  best coin counts and "visited" marks go to `mods-saves/<Mod>.json` in the user directory,
  per user file (`mario1`, `luigi1` …), written when the game saves your file and read when
  it loads it. Here the port adds: they are **cleared when a file is created or deleted and
  copied with it** (`SaveDataHandler.cpp`, `ModGalaxy::clearRecords`/`copyRecords`), in the
  sidecars of every mod, also those that are off, so a new file never inherits another's mod
  stars. `GameData.bin` stays exactly what the game alone would write, so it also works in
  Dolphin, Nebula or on a Wii (`native/tools/convert_save.py`).
- **The star count:** a mod's stars do not count for the game's own goals (domes,
  Grand Stars, the 120-star ending) or its star total; the port counts them apart (the
  hazelnut counter).
- **Unlocking:** a registered galaxy is open from the start, and nothing about it goes
  into the game's flags.
- **Off again:** without the mod its galaxy, miniature and texts are simply gone; its
  progress waits in `mods-saves/` for when it is turned on again.

Saves of the earlier port version kept this progress in `ModProgress/<slot>.txt`. At the first
start the port moves each line into `mods-saves/` once its galaxy is registered, never over a record
that is already there, and renames the folder `ModProgress.migrated` when every line is over
(`platform_host.cpp`).

What a mod still shares with the game: lives, coins and Star Bits collected in its
galaxy count as in any other. A mod that changes one of the game's own levels (not
a new galaxy) changes that level, and its stars count as the game's.

## How the port does it

The registry (upstream): `native/platform/dvd/mod_galaxy.cpp` reads the `galaxy.json` files
and keeps the save sidecars; the game asks it for names (`MessageHolder.cpp`), music
(`AudSceneMgr.cpp`, `AudStageBgmTable.cpp`, `AudStageBgmWrap.cpp`), flags, totals and the
records (`GameDataGalaxyStorage.cpp`, `GameDataHolder.cpp`). On top of it:

- `native/app/platform_host.cpp`: the mods' `messages.txt` and which object archives a mod
  adds. The game code reaches them through `native/include/petari/mod_galaxies.hpp`, whose
  `isMod` asks the registry.
- `MessageHolder.cpp`: after the registry's names and the disc, the mods' text.
- `SaveDataHandler.cpp`: a mod galaxy's records cleared and copied with the user file;
  `GameDataHolder.cpp`: a loaded file starts its mod galaxies blank before their records.
- `NameObjFactory.cpp`: a mod's `Mini<Galaxy>` of a galaxy the registry does not have is left
  out of the dome.
- `NameObjFactory.cpp`, `MiniatureGalaxyHolder.cpp`, `MiniatureGalaxy.cpp`,
  `AstroDomeOrbit.cpp`: `Mini<Galaxy>` miniatures, six to eight orbits in a dome.
- `PowerStar.cpp`: the theme colour for stars in mods' galaxies, and the one brought back
  to the observatory; `ModStarCounter.cpp`, `CounterLayoutController.cpp`: their counter;
  `GameDataFunction.cpp`, `GameDataGalaxyStorage.cpp`: the count.
- `SuperSpinDriver.cpp`, `SpinDriverPathDrawer.cpp`, `NameObjFactory.cpp`: the hazelnut
  Launch Star `SuperSpinDriverHazel`.
- `NameObjFactory.cpp`: a mod's own object archive placed by name is a planet (`PlanetMap`);
  `GuglisStarAppear`, a challenge's star.

Testing a mod's galaxy without the observatory: `--test-fixture stage` with
`PETARI_STAGE=<Galaxy>` accepts a galaxy that a mod in the user directory adds and
registers. The
smoke run's `PETARI_MECHANIC=modstar` plays the planet's challenge
(`PETARI_STAGE=GuglisPlanetGalaxy`, `PETARI_MOD_FOLDERS=GuglisPlanet`): it breaks the three
boxes and collects the star. With `PETARI_STAGE_AFTER_FRAMES=<frames>` the run goes on
that long afterwards, tapping A, through the return to the observatory.
`PETARI_MECHANIC=launchstar` (any stage, with `PETARI_STAGE_WARP` near the star) flies the
nearest Launch Star and checks the landing against `PETARI_MECHANIC_TARGET=x,y,z`: e.g.
`PETARI_STAGE=AstroGalaxy`, warp `5450,300,450`, target `10300,270,-900` (garden to island).
`PETARI_MECHANIC=talk` walks to the person at `PETARI_MECHANIC_TARGET` and talks to them:
the island's Toad with warp `10600,450,-900`, target `10150,260,-1250`. The log names a
mod's line (`[mods] message AstroGalaxy_Kinopio200 from a mod`);
`PETARI_SURFACE_DUMP_LABELS=talk` takes pictures of the talk.

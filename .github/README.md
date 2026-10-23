# MacioGalaxy · Guglis Edits

A fork of [classicrob/MacioGalaxy](https://github.com/classicrob/MacioGalaxy), the
unofficial native Apple Silicon port of Super Mario Galaxy built from the
[Petari](https://github.com/SMGCommunity/Petari) decompilation.

**This fork exists to support the main project, not to replace it.** The port itself, and
everything that makes it work, comes from MacioGalaxy, Petari and Aurora. I really appreciate
the work that has gone into them.

The Guglis Edits are individual adjustments on top of it, one commit each. When an edit is
finished and useful for everyone, it goes to the main project as a pull request, as the
volume slider, fullscreen and the Honeyhive fix already have.

For requirements, game data, building and playing, see the
[MacioGalaxy README](https://github.com/classicrob/MacioGalaxy#readme). Like the main project,
this fork is not affiliated with Nintendo or the Petari project and contains no game data.
Please report problems with the edits below here, not upstream and not to Petari.

## The edits

The branch `guglis-edits` is the official `main` plus three kinds of edits, kept apart:

- **Bug fixes** make the game behave as it did on the Wii, or fix the port. All of them are meant for
  the official repository.
- **Improvements** change controls, presentation and performance, not the game's content. The
  generally useful ones are proposed upstream.
- **Content mods** change or extend the game itself. They are off by default and stay in this fork.

### Bug fixes

| Edit | What it does | Upstream |
| --- | --- | --- |
| macOS library memory fix | Memory that macOS libraries (CoreAudio, Core Animation) allocate on the game thread stays out of the game's heaps; the game crashed when macOS freed it on one of its own threads, for example with AirPods at the first sound | prepared, not submitted: branch `fix-framework-allocations` |

### Improvements

| Edit | What it does | Upstream |
| --- | --- | --- |
| Volume slider | Master volume in the F1 menu, in 5% steps; saved in `sound.txt` when the menu closes | [PR #1](https://github.com/classicrob/MacioGalaxy/pull/1) |
| Fullscreen | Cmd+Return switches to real fullscreen and hides the Mac cursor | [PR #2](https://github.com/classicrob/MacioGalaxy/pull/2) |
| Instant pointer | A switch in F1 → Mods: the Star Pointer is drawn where the mouse points in every frame, without the Wii Remote's smoothing | not yet proposed |
| Graphics page | F1 → Graphics: frame rate, input latency, render at 480p (the Wii's), 720p, 1080p, 1440p, 4K or the display's resolution; FSR 1, bicubic or bilinear upscaling; RCAS sharpening; FXAA; a stats overlay with FPS and a frame time graph | not yet proposed |
| 120 fps | F1 → Graphics → Frame rate 120 (a prototype): an extra frame between two game steps, with the camera and models halfway | not yet proposed |
| Input latency | F1 → Graphics → Input latency Reduced: each game step is drawn in its own frame instead of the next, with fresher input; a key press shows about 17 ms sooner; at 120 fps the extra frame comes first | prepared, not submitted: branch `input-latency` |

### Taken over upstream

The Honeyhive lawn fix (merged as PR #3), the Comet Observatory talk fix (upstream has its own,
equivalent fix) and V-Sync (upstream now always runs the game's clock from the display) are no
longer separate edits.

### Content mods

| Edit | What it does | Upstream |
| --- | --- | --- |
| FineFur | Mod (F1 → Mods): finer fur on the Honey Queen and the bees at high resolutions | not yet proposed |
| Skip the strap screen | Mod (F1 → Mods): the game starts without the Wii Remote strap reminder, which otherwise stays at least 7.5 seconds | not proposed |
| Cheats | F1 → Mods → Cheats: set the 1-Ups (1 to 99); with Keep 1-Ups when loading (on), a loaded file keeps its saved count instead of starting with 4 | not proposed |
| Custom galaxies | Disc-file mods can add whole galaxies: a miniature in an observatory dome, names and dialogue from a `messages.txt`, new objects with their own logic; their progress is kept apart from the save file. Example: `native/tools/make_example_galaxy.py`; a planet modelled in Blender, with an opening flight, a small challenge and its own star counted apart: `native/mods/GuglisPlanet/build.py`. Docs in `native/CUSTOM_GALAXY.md` | not yet proposed |
| Theme colour | The mods' own things are hazelnut brown: the stars of mods' galaxies, their counter under the star counter, and a Launch Star `SuperSpinDriverHazel` with a hazelnut flight path; the game's own colours stay (`native/mods/theme.py`) | not yet proposed |
| Observatory sky island | Mod: a floating island east of the Luma garden, modelled in Blender (`native/mods/Sternenschiff`), with a Toad, Star Bits and hazelnut Launch Stars there and back; the observatory edited in Whitehole through MCP | not yet proposed |
| Galaxy editor in Blender | A Blender add-on: open a galaxy (disc and mods, found by its name in the game) with the game's models and textures, edit objects, map parts, gravity, areas and paths with Blender's tools, save the changed zones as a mod and play them headless or in the game (`native/blender/README.md`) | not yet proposed |

The edits are rebased onto every new official version. Maintenance notes, in German:
[guglis/README.md](https://github.com/rzrnr/MacioGalaxy/blob/guglis-edits/guglis/README.md).

## Credits

Everything here builds on the projects listed under
[Credits and licenses](https://github.com/classicrob/MacioGalaxy#credits-and-licenses) upstream.
The app icon's background is the [Pinwheel Galaxy (M101)](https://commons.wikimedia.org/wiki/File:M101_hires_STScI-PRC2006-10a.jpg),
credit [ESA/Hubble](https://esahubble.org/), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
cropped and tinted. The Graphics page's FSR 1 shaders port
[AMD FidelityFX Super Resolution 1.0](https://github.com/GPUOpen-Effects/FidelityFX-FSR) (MIT).

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

The branch `guglis-edits` is the official `main` plus these edits:

| Edit | What it does | Upstream |
| --- | --- | --- |
| Volume slider | Master volume in the F1 menu, in 5% steps | [PR #1](https://github.com/classicrob/MacioGalaxy/pull/1) |
| Fullscreen | Cmd+Return switches to real fullscreen and hides the Mac cursor | [PR #2](https://github.com/classicrob/MacioGalaxy/pull/2) |
| Honeyhive lawn fix | Keeps negative texture LOD biases on arm64, so the grass is textured again | [PR #3](https://github.com/classicrob/MacioGalaxy/pull/3) |
| macOS library memory fix | Memory that macOS libraries (CoreAudio, Core Animation) allocate on the game thread stays out of the game's heaps; the game crashed when macOS freed it on one of its own threads, for example with AirPods at the first sound | not yet proposed |
| Observatory talk fix | The Comet Observatory's NPCs read their progress flags again: the Mail Toad hands over his letters, and the Toads, Rosalina and the Lumas say the lines for the current progress | not yet proposed |
| FineFur | Mod (F1 → Mods): finer fur on the Honey Queen and the bees at high resolutions | not yet proposed |
| Custom galaxies | Disc-file mods can add whole galaxies: a miniature in an observatory dome, names and dialogue from a `messages.txt`, new objects with their own logic; their progress is kept apart from the save file. Example: `native/tools/make_example_galaxy.py`; a planet modelled in Blender, with an opening flight, a small challenge and a purple star counted apart: `native/mods/GuglisPlanet/build.py`. Docs in `native/CUSTOM_GALAXY.md` | not yet proposed |
| Instant pointer | Mod (F1 → Mods): the Star Pointer is drawn where the mouse points in every frame, without the Wii Remote's smoothing | not yet proposed |
| Graphics page | F1 → Graphics: 120 frames per second with interpolated frames (a prototype); V-Sync (on, low latency, or variable refresh on ProMotion in fullscreen), the game's clock following the display, against micro-stutter; Input latency Reduced, each game step drawn in its own frame instead of the next; render at 480p (the Wii's), 720p, 1080p, 1440p, 4K or the display's resolution; FSR 1, bicubic or bilinear upscaling; RCAS sharpening; FXAA; a stats overlay with FPS and a frame time graph | not yet proposed |

The edits are rebased onto every new official version. Maintenance notes, in German:
[guglis/README.md](https://github.com/rzrnr/MacioGalaxy/blob/guglis-edits/guglis/README.md).

## Credits

Everything here builds on the projects listed under
[Credits and licenses](https://github.com/classicrob/MacioGalaxy#credits-and-licenses) upstream.
The app icon's background is the [Pinwheel Galaxy (M101)](https://commons.wikimedia.org/wiki/File:M101_hires_STScI-PRC2006-10a.jpg),
credit [ESA/Hubble](https://esahubble.org/), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
cropped and tinted. The Graphics page's FSR 1 shaders port
[AMD FidelityFX Super Resolution 1.0](https://github.com/GPUOpen-Effects/FidelityFX-FSR) (MIT).

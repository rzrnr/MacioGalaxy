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
| FineFur | Mod (F1 → Mods): finer fur on the Honey Queen and the bees at high resolutions | not yet proposed |

The edits are rebased onto every new official version. Maintenance notes, in German:
[guglis/README.md](https://github.com/rzrnr/MacioGalaxy/blob/guglis-edits/guglis/README.md).

## Credits

Everything here builds on the projects listed under
[Credits and licenses](https://github.com/classicrob/MacioGalaxy#credits-and-licenses) upstream.
The app icon's background is the [Pinwheel Galaxy (M101)](https://commons.wikimedia.org/wiki/File:M101_hires_STScI-PRC2006-10a.jpg),
credit [ESA/Hubble](https://esahubble.org/), licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
cropped and tinted.

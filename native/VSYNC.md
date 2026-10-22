# V-Sync

The Wii shows a frame on every retrace of the TV, 59.94 times a second. The port's
VI retrace clock is its own timer at 59.94 Hz, and without V-Sync each frame is
handed to the window as soon as it is drawn (present mode Immediate). A Mac display
refreshes at 60 or 120 Hz on its own clock: the two drift against each other, and
for a few seconds out of every half minute or so frames meet the refreshes
unevenly, one shown twice and the next one skipped. That is felt as micro-stutter.

`PETARI_VSYNC` chooses:

| Value | What it does |
| --- | --- |
| `on` (the default) | The retrace clock follows the display's refreshes, and each frame is shown on a fixed refresh. |
| `lowlatency` | As `on`, with each retrace moved as close to the refresh that shows its frame as the draw times allow. |
| `off` | The previous behaviour: the game's own clock, frames shown at once. |

## How it works

- A display link (`native/app/display_link.cpp`) reports every refresh of the
  window's display, and the retrace clock (`native/platform/vi/vi_host.cpp`,
  `petari/display_sync.hpp`) raises its retraces on those refreshes: on every one
  at 60 Hz, on every second one at 120 Hz. The game then runs 0.1% faster on a
  60.00 Hz display than on the Wii's 59.94; sound is not affected.
- While the retraces follow the display, frames are presented in order on
  refreshes (FIFO), and each frame is shown a fixed time after its step's
  retrace, whatever its draw time: one retrace later, on a 120 Hz display the
  second refresh after the retrace. A frame is presented in a window from 1 ms
  after the refresh before its own to 3 ms before its own; one that is ready
  early waits. Without that, a frame drawn in 7 ms and the next in 9 ms land on
  different refreshes of a 120 Hz display: one stays 8 ms, the next 25.
- The display link's refresh times scatter around the display's real, regular
  refreshes (a quarter of a millisecond on average, up to almost one on an M3
  Pro's 120 Hz display); the clock keeps a smoothed grid of them.
- `lowlatency` raises each retrace later after its refresh: a quarter of a
  millisecond more after every 60 steps whose frames were all in time, a
  millisecond less after one that was not, never closer than 7 ms before the
  step's frame is due. The game then reads its input closer to the refresh that
  shows the result.
- Displays at other rates (75, 100, 144 Hz) keep the game's own timer and
  immediate presents, as with `off`. So does the game when the display link
  stops.

## Measured

EggStarGalaxy stage smoke runs on the built-in 120 Hz display of an M3 Pro, about
4,000 frames each:

| `PETARI_VSYNC` | Frames on screen for exactly two refreshes |
| --- | --- |
| `off` | 93.7% (the rest one or three) |
| `on` | 99.5% |
| `lowlatency` | 98.6% |

The frame time report (`PETARI_FRAME_STATS=1` or `PETARI_TRACE_BOOT=1`) has a
`Petari display` line with these counts, worked out from the display link's
refresh times, and a line with the percentiles of the intervals between
presents.

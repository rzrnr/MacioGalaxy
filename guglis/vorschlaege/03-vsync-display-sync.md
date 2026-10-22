## Problem

The VI retrace clock runs on its own 59.94 Hz timer, and frames are handed to the window at once (present mode Immediate). A Mac display refreshes at 60 or 120 Hz on its own clock, so the two drift against each other. For a few seconds out of every half minute or so, frames meet the refreshes unevenly: one is shown twice, the next one skipped. Players feel this as micro-stutter.

## Change

`PETARI_VSYNC=on` (the default), `lowlatency` or `off`. The documentation is in `native/VSYNC.md`.

- **Display link.** A CVDisplayLink on the window's display (`native/app/display_link.cpp`) reports every refresh. VI raises its retraces on those refreshes: every one at 60 Hz, every second one at 120 Hz (`petari/display_sync.hpp`, `vi_host.cpp`).
  - Retraces follow a smoothed grid of the reported times, because the reports scatter by up to a millisecond.
  - Displays at other rates (75, 100, 144 Hz) keep the timer, and so does the game when the link stops.
- **Presenting.** While the retraces follow the display, frames are presented FIFO.
  - Each frame lands on a fixed refresh, one retrace after its step's retrace, whatever its draw time.
  - Its present falls in a window from 1 ms after the refresh before its own to 3 ms before its own.
- **`lowlatency`.** It raises the retraces later after their refresh, as far as the draw times allow: a quarter of a millisecond per 60 clean steps, a millisecond back after a late frame.
- **Frame time report.** It adds the number of refreshes each frame stayed on screen and the present interval percentiles.

## Measured

Built on this branch alone. EggStarGalaxy stage smoke, headless, on an M3 Pro's 120 Hz display, about 4,000 frames per run:

| `PETARI_VSYNC` | Frames on screen for exactly two refreshes |
| --- | --- |
| `off` (the previous behaviour) | 93.7% |
| `on` | 99.5% |
| `lowlatency` | 98.6% |

## Testing

- All 84 ctest programs pass. `platform_vi_tests` adds checks for the refresh grid and for which display rates are followed.
- The stage smokes pass in all three modes.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

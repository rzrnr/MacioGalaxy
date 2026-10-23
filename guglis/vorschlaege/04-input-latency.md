## Problem

A press takes about two frames to reach the screen, for two reasons:

- **Event timing.** The frame seam pumps SDL events once per frame, after the present. The virtual Wii Remote then reports every 5 ms. A key pressed just after the seam waits for the next frame's seam, and then for the next report.
- **Frame order.** The Wii's frame order draws a step in the frame after its update.

## Change

- **Fresh input (always on).** Right before a step reads its controllers, the seam passes the game the key, mouse and controller events that arrived since its last pump. They are peeked, so ImGui and the window still see each one once.
  - `Input::sampleNow` then builds a report at once.
  - The 200 Hz report tick restarts from that report, so reports keep their 5 ms spacing.
- **`PETARI_INPUT_LATENCY=reduced` (opt-in).** It runs `GameSystem::frameLoopInputFirst`: update, then calcAnim, then the draw of that same step, so the result is on screen one frame sooner.
  - Game logic is unchanged.
  - Draw-sync token data is still read by the next step's update.
  - The default keeps the Wii's order.
- **Latency probe.** It now takes the first display copy after the step that read the press has finished calcAnim (frame mark `PETARI_FRAME_MARK_UPDATED`), so both orders are measured the same way.

Documentation is in `native/INPUT_LATENCY.md` and the README section "Input latency".

## Measured

Built on this branch alone. EggStarGalaxy stage smoke on an M3 Pro, with `PETARI_LATENCY_PROBE=1 PETARI_LATENCY_TEST=1`, 30 presses of A. The figure is the median time from press to present:

| Frame order | Press to present |
| --- | --- |
| Wii's (default) | 33.0 ms |
| `reduced` | 15.6 ms |

## Testing

- All 84 ctest programs pass. The seam tests gain fakes for `SDL_PumpEvents`, `SDL_PeepEvents` and `Input::sampleNow`.
- The stage smokes pass in both orders.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

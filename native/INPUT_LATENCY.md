# Input latency

Two changes bring input to the screen sooner.

## Reduced frame order (F1 → Graphics → Input latency: Reduced)

The Wii's frame loop (`GameSystem::frameLoop`) draws, at the start of each frame,
the step it computed in the frame before, and then computes the next step while
the GPU draws: on the Wii both ran at once. A button pressed now is read by the
next step and shown a frame after that.

With Input latency Reduced (`InputLatency=reduced` in `graphics.txt`) the loop (`GameSystem::frameLoopInputFirst`)
computes the step first and draws it at once, in the same frame: the same work,
one frame (16.7 ms) sooner on screen. Game logic is unchanged. What the draw-sync
token callbacks (the Star Pointer's and lens flares' EFB reads, the talk
balloons') write is read by the next step, as before, and the screen preserver's
capture still follows the draw. The default, Original, keeps the Wii's order.
`PETARI_INPUT_LATENCY=reduced|original` overrides the setting for one run.

At Frame rate 120 (native/FRAME_RATE.md) the extra frame then comes before the
step's frame: it is drawn between calcAnim and the draw and presented first, and
the step's frame follows half a field later.

## Fresh input (always on)

The frame seam pumps SDL events once per frame, after the present. A key pressed
just after it waited for the next frame's seam, and then for the next 5 ms report
of the virtual Wii Remote. Now:

- Right before the step reads its controllers (after the retrace), the seam hands
  key, mouse and controller events that came since its last pump to the game
  (`takeInputEarly` in `native/app/frame_seam.cpp`). They are peeked, not taken:
  aurora_update still delivers them to ImGui and the window handling, and the
  seam skips them for the game the second time.
- `Input::sampleNow` (`native/input/wpad_host.cpp`) then builds a Wii Remote report
  at once if input came since the last one. The 200 Hz report tick restarts from
  that report, so reports keep their 5 ms spacing; the remote model's
  time-stepped motions (shake, tilt, the stick's pointer) see one shorter step when
  input arrives.

## Measuring

`PETARI_LATENCY_PROBE=1 PETARI_LATENCY_TEST=1`: during gameplay the test presses
A at random moments and logs, for each press, the time from the press to the
first presented frame that can show the response (`[latency]` lines). The probe
takes the first display copy after the step that read the press finished its
calcAnim (the frame mark `PETARI_FRAME_MARK_UPDATED`), so it measures both loop
orders the same way.

Measured on an M3 Pro (Good Egg stage runs, 30 presses each, press to
present, median):

| Frame order | Press to present |
| --- | --- |
| Wii's (original) | 33.0 ms |
| reduced | 15.6 ms |

The stage smoke runs, the Comet Observatory included, pass in both orders.

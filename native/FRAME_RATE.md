# Frame rate and V-Sync

F1, then **Graphics**: **Frame rate** 60 or 120 (interpolated), a prototype, and
**V-Sync** on or off.

The game itself always runs at 60 steps per second (59.94 Hz, as on the Wii):
Mario, enemies, physics and timers are unchanged. At 120, the game draws one
more frame between every two steps, with the camera and every model halfway
between them, and shows it half a step later. Movement and camera turns look
twice as smooth; the game does not react faster.

## What it needs

- A display that shows 100 frames per second or more: the built-in display of a
  MacBook Pro (ProMotion, 120 Hz) or an external 120 or 144 Hz monitor. On a
  60 Hz display no extra frames are drawn and the game looks as at 60; the
  setting is kept for when the window is on a faster display (checked once a
  second). The Graphics page then shows "Frame rate: 120 (60 Hz display)" and
  says why.
- GPU time for a second frame per step. The extra frame costs about as much as
  the step's own frame (about 2 ms at 720p on an M3 Pro). When a step's frame
  comes late, that step gets no extra frame. A lower Resolution
  (native/GRAPHICS.md) leaves more room.

With Stats on, FPS counts every frame shown, the extra frames too; the frame
time graph has lines at 60 and 120 frames per second. Stats Detailed adds a
line at 120: the share of the last second's steps that got an extra frame and
the share that came too late for one, or why there are none (a display below
100 Hz; "here" when the scene asks for none, as in movies).

## V-Sync

The Wii shows a frame on every retrace of the TV, 59.94 times a second. Without
V-Sync the game's retrace clock is its own timer at 59.94 Hz, and each frame is
handed to the window as soon as it is drawn. A Mac display refreshes at 60 or
120 Hz on its own clock: the two drift against each other, and for a few
seconds out of every half minute or so frames meet the refreshes unevenly, one
shown twice and the next one skipped. That is felt as micro-stutter.

F1 → Graphics → **V-Sync** has four choices (`VSync=` in `graphics.txt`):

| V-Sync | What it does | For |
| --- | --- | --- |
| Off | The game's own 59.94 Hz clock; each frame goes to the window as soon as it is drawn. | the lowest latency, uneven |
| On (default) | The game's clock follows the display, and each frame is shown on a fixed refresh. | smooth on any 60 or 120 Hz display |
| Low latency | As On, with the clock moved as close to the refreshes as the draw times allow, found by the game itself. | smooth with less latency, at Frame rate 60 most |
| Variable | On a ProMotion or Adaptive-Sync display in fullscreen the display follows the game's own clock: each frame is shown when it is ready. Elsewhere as On, and the Graphics page says so. | the MacBook display in fullscreen |

On and Low latency:

- A display link (`native/app/display_link.cpp`) reports every refresh of the
  window's display, and the retrace clock (`native/platform/vi/vi_host.cpp`,
  `petari/display_sync.hpp`) raises its retraces on those refreshes: on every
  one at 60 Hz, on every second one at 120 Hz. The game runs 0.1% faster on a
  60.00 Hz display than on the Wii's 59.94; sound is not affected.
- Frames are presented in order on refreshes (FIFO), and each frame is shown a
  fixed time after its step's retrace, whatever its draw time: the step's frame
  one retrace later (on a 120 Hz display the second refresh after the retrace),
  the extra frame at Frame rate 120 half a retrace after that. Each frame is
  presented in a window from 1 ms after the refresh before its own to 3 ms
  before its own; one that is ready early waits for its window. Without that, a
  frame drawn in 7 ms and the next in 9 ms land on different refreshes: one
  stays 8 ms, the next 25.
- The display link's refresh times scatter around the display's real, regular
  refreshes (by a quarter of a millisecond on average, up to almost one on an
  M3 Pro's 120 Hz display); the clock keeps a smoothed grid of them.
- Low latency raises each retrace later after its refresh: a quarter of a
  millisecond more after every second (60 steps) in which every frame was in
  time, a millisecond less after a frame that was not, never closer than 7 ms
  before the step's frame is due. The game then starts a step closer to the
  refresh that shows it.
- Displays at other rates (75, 100, 144 Hz) keep the game's own timer, as with
  V-Sync off. So does the game when the display link stops.

Variable:

- The game keeps its own 59.94 Hz clock, frames are presented in FIFO order,
  and the step's frame is presented a fixed time after its retrace, the extra
  frame half a retrace later. That time starts at 8 ms; a frame that is late
  adds half a millisecond, a second without one takes a tenth away (3 to 14 ms).
- It needs a display whose refresh can vary (NSScreen's maximum refresh
  interval longer than its minimum: ProMotion, Adaptive-Sync) and the game in
  fullscreen; macOS only lets a fullscreen game drive the refresh.
  `PETARI_VARIABLE_REFRESH=1` uses it anywhere, for measuring its pacing.

## Input latency

F1 → Graphics → **Input latency**: Original or Reduced (`InputLatency=` in
`graphics.txt`, default Original).

The Wii's frame loop (`GameSystem::frameLoop`) draws, at the start of each
frame, the step it computed in the frame before, and then computes the next
step while the GPU draws: on the Wii both ran at once. A button pressed now is
read by the next step and shown a frame after that.

Reduced (`GameSystem::frameLoopInputFirst`) computes the step first and draws
it at once, in the same frame: the same work, one frame (16.7 ms) sooner on
screen. Game logic is unchanged; what the draw-sync token callbacks (the Star
Pointer's and lens flares' EFB reads, the talk balloons') write is read by the
next step, as before. At Frame rate 120 the extra frame, halfway between the
step drawn last and this one, comes first, and this step's frame half a step
after it.

In both orders the frame seam also hands keys, mouse and controller input that
came since its last event pump to the game right before the step reads its
controllers (`takeInputEarly` in `native/app/frame_seam.cpp`), and
`Input::sampleNow` puts it into a Wii Remote report at once instead of up to
5 ms later. The remote's 200 Hz report tick restarts from that report, so the
remote model's time-stepped motions keep their pace.

`PETARI_LATENCY_PROBE=1 PETARI_LATENCY_TEST=1` measures it: during gameplay the
test presses A at random moments and logs, for each press, the time to the
first presented frame that can show the response (`[latency]` lines).

## What moves at 120

- The camera: position, orientation, field of view and camera shake.
- Every J3D model drawn in both steps: its placement and every joint. Rotation
  is blended along the shortest arc (quaternions), translation and scale
  linearly. That covers Mario, enemies, items, moving platforms and planets.

## What stays at 60

- Particle effects, shadows, texture animations, water surfaces, and drawn
  geometry that is not a J3D model (ropes, Mario's and enemies' fur). They show
  the newer step in the extra frame, a half step ahead of the models.
- Mirror and water reflections show the newer step's reflection.
- The 2D HUD and menus.
- Cuts: when the camera moves more than 1500 units or turns more than 45 degrees
  in one step, that step gets no extra frame. A model that moves more than 1000
  units in one step was placed, not moved, and is drawn at its new place.
- Movies and the title's loading screens: no extra frames.

## Settings

`graphics.txt` (native/GRAPHICS.md) keeps the choices as `FrameRate=60` or
`FrameRate=120` (default 60), `VSync=off`, `on`, `lowlatency` or `variable`
(default on) and `InputLatency=original` or `reduced` (default original). For
one run: `PETARI_GRAPHICS=FrameRate=120,VSync=off`.

The frame time report (`PETARI_FRAME_STATS=1` or `PETARI_TRACE_BOOT=1`) counts
the steps without an extra frame and, from the display link's refresh times,
how many refreshes each frame stayed on screen, judged by when it was presented.

Measured on the built-in 120 Hz display of an M3 Pro (Good Egg stage runs,
about 4,000 game steps each):

| | V-Sync off | V-Sync on |
| --- | --- | --- |
| Frame rate 60, 1080p: frames on screen for exactly two refreshes | 92% | 99.7% |
| Frame rate 120, 1080p: steps without an extra frame | 11% | 2% |
| Frame rate 120, 1440p: steps without an extra frame | 13% | 3% |

Without V-Sync the other frames stay one or three refreshes, and the extra
frames' refreshes vary with the draw times; with V-Sync each extra frame has
its refresh.

With FXAA the frames cost more: at 1440p 5 to 9% of the steps get no extra
frame, at 4K about a third. There two frames per step no longer fit the GPU's
16.7 ms, whatever the V-Sync mode; a lower Resolution with FSR 1 helps.

## How it works

The game's frame loop (`GameSystem::frameLoop`) draws step k-1, then computes
step k: the update, then `calcAnim`, which calculates every joint and view
(`SceneFunction::executeCalcViewAndEntryList`). Frame interpolation
(`src/Game/System/FrameInterpolation.cpp`) adds:

1. Before the update, the camera and every model's placement and joints as they
   were drawn for step k-1. Every model's view calculation (`J3DModel::viewCalc`,
   Mario's `J3DModelX` views) records which models were drawn.
2. After step k-1's frame was presented, the same for step k. Camera and joints
   are set halfway, the views are calculated again, and the game's draw runs a
   second time into its own display copy (`MainLoopFramework::drawExtraFrame`).
3. Step k is put back exactly: joints, camera and views as `calcAnim` left them,
   Mario's actor state (his view calculation has side effects) and the random
   number generator. Draw code that must run once per step (the lens flare's
   and Star Pointer's draw-sync tokens, the talk balloons' token, the
   snapshot for the Wii Message Board) skips the extra frame.
4. With V-Sync the extra frame is presented at once and shown on the refresh
   after step k-1's frame (`syncedPresentDue` in `native/app/frame_seam.cpp`).
   Without, it is presented half a step (8.3 ms) after step k-1's frame
   (`petari_host_present_seam`), so that the frames come evenly at 120 per
   second.

The extra frame changes nothing in the game state that the next step reads.
Checked: the stage smoke runs (Good Egg, Honeyhive) pass at 120, and the camera
in the extra frame lies exactly halfway in every step. Not yet checked: a
frame-exact comparison of a recorded movement run at 60 and 120, and every
actor class with its own view calculation (mirrors, part models, rail blocks).

## Why not more than 120

Each extra frame is a full draw of the scene. At 240 the GPU would draw four
frames per step; even at 720p that does not fit on an M3 Pro.

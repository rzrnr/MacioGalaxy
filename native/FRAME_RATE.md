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

With V-Sync on (the default):

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
- Displays at other rates (75, 100, 144 Hz) keep the game's own timer, as with
  V-Sync off. So does the game when the display link stops.

V-Sync off gives the lowest latency, as before this option: frames go to the
display at once, unevenly.

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
`FrameRate=120` (default 60) and `VSync=on` or `VSync=off` (default on). For one
run: `PETARI_GRAPHICS=FrameRate=120,VSync=off`.

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

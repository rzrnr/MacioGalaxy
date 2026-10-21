# Graphics page

F1, then **Graphics**: the frame rate, the resolution the game renders at, how
the image is scaled to the window, sharpening, anti-aliasing, and an optional
stats overlay.
Every change shows at once, while the game keeps running behind the menu. The
defaults draw exactly as before.

| Item | Choices | What it does |
| --- | --- | --- |
| Frame rate | 60, 120 (interpolated) | At 120 the game draws one extra frame between every two of its 60 steps per second, with the camera and the models halfway, for smoother motion on a 120 Hz display. A prototype; native/FRAME_RATE.md has what it needs and what stays at 60. |
| Resolution | Display, 480p (Wii), 720p, 1080p, 1440p, 4K | The render height, at the displayed image's aspect (16:9: 853 x 480, 1280 x 720, 1920 x 1080, 2560 x 1440, 3840 x 2160). The same choice gives the same image on every Mac. Display renders at the displayed image's own size. Below the displayed size the image is upscaled (faster); above it, it is supersampled (smoother edges, more GPU time). 480p is the Wii's own resolution. |
| Upscaler | FSR 1, Bicubic, Bilinear | The filter while upscaling. FSR 1 (AMD FidelityFX Super Resolution 1.0, EASU) keeps edges sharp and clean; bicubic (Catmull-Rom) is sharper than bilinear, which is what the window used before. At 1:1 nothing is scaled; when supersampling an area filter in linear light shrinks the image. |
| Sharpening | Off, Low, Medium, High | FSR 1's RCAS sharpening after scaling, at any resolution. Low, Medium and High are AMD's 1, 0.5 and 0.2 stops. High also sharpens noise and the HUD. |
| Anti-aliasing | Off, FXAA | Smooths stair-stepped edges at the render resolution, before the image is scaled. |
| Stats | Off, FPS, Detailed | An overlay at the top of the image. FPS: frames per second. Detailed: frame time and the worst frame of the last three seconds, a frame time graph (lines at 60 and 120 frames per second), where the frame's time goes, and the render size. While Stats is on, the window title shows the frames per second too. |

The page's message line shows both sizes and what happens between them, for
example "Renders 1920 x 1080, shown at 2560 x 1440 (upscaled)".

Left/Right change the focused value, A steps it, Back or Escape returns to the
list.

## graphics.txt

The page saves every change in `graphics.txt` in the user directory:

```
FrameRate=60
Resolution=1080
Upscaler=fsr1
Sharpening=low
AntiAliasing=off
Stats=fps
```

A missing file keeps the defaults (`FrameRate=60`, `Resolution=display`, `Upscaler=fsr1`,
`Sharpening=off`, `AntiAliasing=off`, `Stats=off`). Resolution also takes
`1080p` or `4k`; another height takes the nearest choice. A damaged file is
reported at startup and changes nothing. For one run, `PETARI_GRAPHICS`
overrides single keys, comma separated:
`PETARI_GRAPHICS=Resolution=720,Upscaler=bicubic`.

## The stats

- **FPS** counts the frames of the last second, at 120 the extra frames too.
- **Game** is the game's own work per step on the CPU, from the retrace to the
  end of the step.
- **GPU wait** is how long the frame's end waits for the GPU to finish drawing.
  It rises when the GPU is the limit; it is not a GPU timer.
- **present** is the time to hand the frame to the window and open the next one.
- At Frame rate 120: **Extra frames** is the share of game steps that got an
  interpolated frame, **too late** the share whose frame came too late for one
  (the GPU is the limit: a lower Resolution helps). On a display below 100 Hz
  the line says so instead (native/FRAME_RATE.md).

The game runs at 60 steps per second; a frame time of 16.7 ms is on target, at
120 (interpolated) 8.3 ms.

## How it works

- The render size is the EFB's size: the patched `aurora::window::get_window_size`
  (`native/gx/patch_aurora_present.py`) gives the EFB the chosen height at the
  displayed image's aspect. Render-to-texture effects (bloom, shadows, screen
  captures) follow the EFB as they do for any window size.
- A Resolution change resizes the frame buffers at the next frame, as a window
  resize does: the game hitches for about a tenth of a second once.
- The present pass (`native/gx/present/present_aurora.cpp`):
  1. FXAA, if on, at the render size into an intermediate texture.
  2. Scaling: straight into the window with Aurora's copy pipeline (1:1 or
     bilinear), the bicubic filter or the area filter. With FSR 1 or
     sharpening the image is scaled into a texture of the window's image size
     first (EASU for FSR 1).
  3. RCAS sharpening (or a copy) from that texture into the window.
- The game's 2D HUD is part of the game image, so it is scaled, sharpened and
  anti-aliased with it. The F1 menu and the stats overlay are drawn on top at
  window size.
- MSAA is not offered: the game reads the EFB back (Star Pointer, lens flares),
  which needs a single-sample EFB.

## Credits

`fs_easu` and `fs_rcas` in `native/gx/present/present_aurora.cpp` port AMD
FidelityFX Super Resolution 1.0 (`ffx_fsr1.h`, the 32-bit `FsrEasuF` and
`FsrRcasF` paths, from
[GPUOpen-Effects/FidelityFX-FSR](https://github.com/GPUOpen-Effects/FidelityFX-FSR))
to WGSL: MIT License, Copyright (c) 2021 Advanced Micro Devices, Inc. The license
text is in the source file. The other filters are written for this port.

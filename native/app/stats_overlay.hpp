#pragma once
// The stats overlay of the F1 menu's Graphics page (native/GRAPHICS.md): frames per
// second over the game image, with frame times, a frame time graph and the render
// size when Stats is Detailed, and the frames per second in the window title.
// Everything here runs on the game (main) thread.

#include <SDL3/SDL_video.h>

namespace PetariNative::App::StatsOverlay {

// One frame, measured at the seam (frame_stats.hpp has the same parts).
struct Sample {
    double intervalMs = 0.0;   // seam to seam
    double workMs = 0.0;       // the game's frame work, retrace to end of frame
    double drawDoneMs = 0.0;   // waiting for the GPU to finish the frame's drawing
    double presentMs = 0.0;    // aurora_end_frame and aurora_begin_frame
};

void addFrame(const Sample& sample);

// Between aurora_begin_frame and aurora_end_frame, with the game image in window
// points. Also tells the Graphics page the image's size in pixels.
void draw(SDL_Window* window, float imageX, float imageY, float imageWidth, float imageHeight);

}  // namespace PetariNative::App::StatsOverlay

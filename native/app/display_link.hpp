#pragma once
// Display sync (petari/display_sync.hpp, native/VSYNC.md): a CVDisplayLink on the
// game window's display reports every refresh, for the VI retrace clock while V-Sync is
// on and for the cadence counts in the frame time report. Follows the window when it
// moves to another display.

#include <SDL3/SDL_video.h>

namespace PetariNative::App::DisplayLink {

// Once a second from the frame seam (game thread): starts the link on the window's
// display or moves it to another display; sync: V-Sync, VI follows the refreshes.
void follow(SDL_Window* window, bool sync);

// Each present (game thread), for the cadence counts in the frame time report.
void notePresent();

// The frame time report: how many refreshes the frames stayed on screen, from the refresh
// each present lands on (DisplaySync::refreshShowing).
void writeReport();

}  // namespace PetariNative::App::DisplayLink

#pragma once
// The level testbed (petari_testbed, native/blender/README.md): one galaxy with the
// game's own scene, objects and controls, and nothing in front of it.
//
// petari_testbed sets these before the game starts; in the game itself they stay off.
// The stage and mission go through the test fixture's entry (test_fixture.hpp:
// TestFixture::stage, stageScenario), the reload through the Level Select's warp
// (player_launch.hpp: PlayerLaunch::warpPending).

#include <atomic>

namespace PetariNative::Testbed {
// No strap screen, title or file select: once the save is mounted, a fresh file
// held only in memory (story through, opening demos seen, no Power Stars at all)
// goes straight to the galaxy. Whatever would leave it for the title or
// the observatory (game over, a star, leaving the galaxy, a reset) starts it again
// on a fresh file instead (GameSequenceProgress::requestGalaxyMove).
inline bool active = false;

// The mission's opening camera flight is skipped as soon as the game allows it (as the
// player's A press would: on a mission already visited, which the testbed's file is).
inline bool skipOpeningCamera = true;

// Set together with a warp to the same stage: the next scene change drops the
// file cache the game keeps for a same-stage restart, so the stage's archives
// are read again (the edited zones). Cleared by the scene change that used it
// (the warp's, or a restart after a miss that comes first).
inline std::atomic<bool> dropFileCache{false};

// Called by that scene change once the old scene is gone and before the next
// one loads (on the game's scene thread): petari_testbed rebuilds the disc's mod
// overlay there.
inline void (*refreshDisc)() = nullptr;

// Set when the mission starts again on a fresh file (game over, star, leaving):
// petari_testbed puts Mario at the Teststart once more.
inline std::atomic<bool> freshStart{false};
}  // namespace PetariNative::Testbed

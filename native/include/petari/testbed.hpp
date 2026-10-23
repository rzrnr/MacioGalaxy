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
// held only in memory (story through, opening demos seen, no stars in the tested
// galaxy) goes straight to the galaxy.
inline bool active = false;

// The mission's opening camera flight is skipped as soon as the game allows it (as the
// player's A press would: on a mission already visited, which the testbed's file is).
inline bool skipOpeningCamera = true;

// Set together with a warp to the same stage: the next scene change drops the
// file cache the game keeps for a same-stage restart, so the stage's archives
// are read again (the edited zones). Cleared by the scene change that used it.
inline std::atomic<bool> dropFileCache{false};
}  // namespace PetariNative::Testbed

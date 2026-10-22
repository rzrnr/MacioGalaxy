#pragma once
// What disc-file mods add beyond upstream's galaxy registry (petari/platform/mod_galaxy.hpp,
// native/CUSTOM_GALAXY.md): their text for NPCs and other messages the disc lacks, the game's
// language for it, and which galaxies are a mod's (the registry's) for the dome miniatures, the
// theme colour and the mods' star counter. native/app/platform_host.cpp sets the hooks when the
// mods are resolved; until then, and in builds of the game code without the app (tests), they are
// null and the game behaves as without mods.
//
// Header-only (C++17 inline variables), as petari/frame_telemetry.hpp: every static library that
// includes it shares one copy in the executable, without a link dependency.

#include <petari/platform/mod_galaxy.hpp>

namespace PetariNative::ModGalaxies {

// The enabled mods' messages.<language>.txt and messages.txt, in precedence order; language may
// be null (then only messages.txt).
inline const char* (*messages)(const char* language) = nullptr;
// The game's language prefix ("UsEnglish"), set by the game code that knows it (Language.cpp).
inline const char* (*languagePrefix)() = nullptr;

// Whether a mod adds this galaxy: a galaxy of the registry (galaxy.json of an enabled mod).
inline bool isMod(const char* galaxy) {
    return galaxy != nullptr && PetariNative::Platform::ModGalaxy::find(galaxy) != nullptr;
}

}  // namespace PetariNative::ModGalaxies

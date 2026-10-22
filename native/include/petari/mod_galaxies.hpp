#pragma once
// Galaxies and text that disc-file mods add (native/CUSTOM_GALAXY.md): the app's side, reached
// from the game code through these hooks. native/app/platform_host.cpp sets them when the mods are
// resolved; until then, and in builds of the game code without the app (tests), they are null and
// the game behaves as without mods.
//
// Header-only (C++17 inline variables), as petari/frame_telemetry.hpp: every static library that
// includes it shares one copy in the executable, without a link dependency.

#include <cstdint>

namespace PetariNative::ModGalaxies {

// The enabled mods' messages.<language>.txt and messages.txt, in precedence order; language may
// be null (then only messages.txt).
inline const char* (*messages)(const char* language) = nullptr;
// The game's language prefix ("UsEnglish"), set by the game code that knows it (Language.cpp).
inline const char* (*languagePrefix)() = nullptr;

// Whether a mod adds this galaxy (its scenario archive is a mod's, not the disc's).
inline bool (*isModGalaxy)(const char* galaxy) = nullptr;
// Whether a mod adds an object archive of this name (ObjectData/<name>.arc, not on the disc): a
// placement of that name with no class of its own is the mod's planet (PlanetMap).
inline bool (*isModObject)(const char* name) = nullptr;
// The original galaxy whose sounds and music a mod galaxy uses; null for other stages.
inline const char* (*soundStage)(const char* galaxy) = nullptr;

// A mod galaxy's progress in a save slot ("mario1"): stars and visited bits, best coin counts.
inline bool (*loadProgress)(const char* slot, const char* galaxy, std::uint8_t* stars, std::uint8_t* visited, std::uint16_t* coins) = nullptr;
inline void (*saveProgress)(const char* slot, const char* galaxy, std::uint8_t stars, std::uint8_t visited, const std::uint16_t* coins) = nullptr;
inline void (*clearProgress)(const char* slot) = nullptr;
inline void (*copyProgress)(const char* dstSlot, const char* srcSlot) = nullptr;

inline bool isMod(const char* galaxy) {
    return isModGalaxy != nullptr && galaxy != nullptr && isModGalaxy(galaxy);
}

inline bool isObject(const char* name) {
    return isModObject != nullptr && name != nullptr && isModObject(name);
}

}  // namespace PetariNative::ModGalaxies

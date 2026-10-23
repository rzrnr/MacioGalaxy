#pragma once
// Cheats (F1 -> Mods -> Cheats, native/MODS.md). For now one: the number of
// 1-Ups, set from the menu, and whether a loaded file keeps its saved 1-Ups.
//
// cheats.txt in the user directory: KeepLives=on|off, default on. A missing
// file keeps the default. Nothing changes on error.

#include <atomic>
#include <filesystem>
#include <string>

namespace PetariNative::Cheats {

bool load(const std::filesystem::path& file, std::string* error);
bool save(std::string* error);  // no-op before load
std::string serialize();
bool parse(const std::string& text, std::string* error);

// The game saves the 1-Ups with the file but starts every load with 4. While
// this is on, a loaded file keeps the saved count (GameDataPlayerStatus).
bool keepLives();  // any thread
void setKeepLives(bool on);

// The 1-Ups of the file in play, published by GameScene::update; -1 outside a
// galaxy (no file in play yet). The menu shows it.
inline std::atomic<int> currentLives{-1};
// A count set from the menu, applied by GameScene::update at its next frame
// through the game's own counter; -1: none pending.
inline std::atomic<int> requestedLives{-1};

void resetForTesting();

}  // namespace PetariNative::Cheats

// Platform start-up and exit for the native application. SDK side: no Aurora
// or SDL headers here.

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <map>
#include <set>
#include <sstream>
#include <system_error>
#include <revolution/dvd.h>
#include <revolution/nand.h>

#include <petari/audio_sdl.hpp>
#include <petari/boot.hpp>
#include <petari/platform/crash.hpp>
#include <petari/platform/diagnostics.hpp>
#include <petari/platform/dvd.hpp>
#include <petari/platform/mod_folder.hpp>
#include <petari/platform/nand.hpp>
#include <petari/platform/os_host.hpp>
#include <petari/platform/power.hpp>
#include <petari/platform/sc.hpp>
#include <petari/platform/vi.hpp>
#include <petari/host_allocation.hpp>
#include <petari/mod_galaxies.hpp>

#include "host.hpp"
#include "smoke.hpp"

extern "C" void petari_game_main(void);          // src/Game/System/GameSystem.cpp
extern "C" void petari_attach_vi_renderer(void);  // native/gx/vi_bridge.cpp
extern "C" void petari_present_install(void);     // native/gx/present/present_host.cpp
extern "C" bool petari_gx_waiting_for_pipeline();  // native/gx/patch_aurora_pipeline.py

namespace PetariNative::App::Host {

namespace Platform = PetariNative::Platform;

namespace {

// The OS exit functions (OSShutdownSystem, OSReturnToMenu, OSRestart, ...)
// end here after the game's shutdown functions ran, on the game thread that
// called them. NAND data is durable once NANDClose/NANDSafeClose returned, so
// nothing needs flushing but stdio; process exit releases the audio device and
// the window, so no platform shutdowns (which join their threads) run here.
void leave(const Platform::Power::Exit& exit, void*) {
    Seam::reportFrameStats();
    petari_platform_report_diagnostics();
    std::fflush(stdout);
    std::fflush(stderr);
    if (exit.intent == Platform::Power::Intent::Restart) {
        Platform::Power::relaunch(exit.resetCode);
        std::fputs("Petari: relaunching failed\n", stderr);
        std::_Exit(1);
    }
    // 0, or the smoke run's result (smoke.hpp) when one decided.
    std::_Exit(Smoke::processExitStatus());
}

// The smoke watchdog's hang report (smoke.hpp).
void dumpHangState(const char* reason) {
    std::fprintf(stderr, "[hang] renderer: blocking pipeline wait %s\n", petari_gx_waiting_for_pipeline() ? "yes" : "no");
    petari_platform_dump_hang_state(reason);
    petari_platform_report_diagnostics();
}

// Enabled disc-file mods in precedence order (priority, then name), for their messages.txt.
std::vector<std::filesystem::path> gEnabledModRoots;
// For mod galaxies (native/CUSTOM_GALAXY.md): the disc paths the mods supply (lower case), the
// disc directory, and the user directory, where ModProgress/ keeps their progress.
std::set<std::string> gModPaths;
std::filesystem::path gDiscRoot;
std::filesystem::path gUserRoot;

std::string lower(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return text;
}

void rememberEnabledMods() {
    std::vector<Platform::ModFolder::ModInfo> mods = Platform::ModFolder::detected();
    const std::map<std::string, bool> states = Platform::ModFolder::detectedStates();
    std::stable_sort(mods.begin(), mods.end(), [](const auto& a, const auto& b) {
        return a.priority != b.priority ? a.priority > b.priority : a.name < b.name;
    });
    gEnabledModRoots.clear();
    for (const auto& mod : mods) {
        const auto state = states.find(mod.name);
        if (state != states.end() && state->second) gEnabledModRoots.push_back(mod.root);
    }
}

}  // namespace

const std::vector<std::filesystem::path>& enabledModRoots() {
    return gEnabledModRoots;
}

// A galaxy a mod adds: an enabled mod supplies its scenario archive and the disc has none.
bool isModGalaxy(const std::string& galaxy) {
    const std::string path = "StageData/" + galaxy + "/" + galaxy + "Scenario.arc";
    if (gModPaths.count(lower(path)) == 0) return false;
    std::error_code ec;
    return !std::filesystem::exists(gDiscRoot / "files" / path, ec) && !std::filesystem::exists(gDiscRoot / "DATA/files" / path, ec);
}

// An object archive a mod adds (ObjectData/<name>.arc, not on the disc).
bool isModObject(const std::string& name) {
    const std::string path = "ObjectData/" + name + ".arc";
    if (gModPaths.count(lower(path)) == 0) return false;
    std::error_code ec;
    return !std::filesystem::exists(gDiscRoot / "files" / path, ec) && !std::filesystem::exists(gDiscRoot / "DATA/files" / path, ec);
}

// ModProgress/<slot>.txt: "<galaxy> stars=<bits> visited=<bits> coins=<8 numbers>" per line.
struct GalaxyProgress {
    unsigned stars = 0, visited = 0;
    unsigned coins[8] = {};
};

std::filesystem::path progressFile(const std::string& slot) {
    return gUserRoot / "ModProgress" / (slot + ".txt");
}

std::map<std::string, GalaxyProgress> readProgress(const std::string& slot) {
    std::map<std::string, GalaxyProgress> progress;
    std::ifstream in(progressFile(slot));
    std::string line;
    while (std::getline(in, line)) {
        std::istringstream fields(line);
        std::string galaxy, field;
        if (!(fields >> galaxy) || galaxy[0] == '#') continue;
        GalaxyProgress entry;
        while (fields >> field) {
            if (field.rfind("stars=", 0) == 0) entry.stars = std::strtoul(field.c_str() + 6, nullptr, 0);
            if (field.rfind("visited=", 0) == 0) entry.visited = std::strtoul(field.c_str() + 8, nullptr, 0);
            if (field.rfind("coins=", 0) == 0) {
                const char* p = field.c_str() + 6;
                for (unsigned& coin : entry.coins) {
                    char* end = nullptr;
                    coin = std::strtoul(p, &end, 10);
                    p = *end == ',' ? end + 1 : end;
                }
            }
        }
        progress[galaxy] = entry;
    }
    return progress;
}

}  // namespace PetariNative::App::Host

// Mod galaxies (native/CUSTOM_GALAXY.md): never in GameData.bin. GameDataAllGalaxyStorage keeps
// them out of the save and out of the star totals, and their progress lives in
// <user>/ModProgress/<slot>.txt, so turning a mod off or on again leaves the save untouched.
extern "C" bool petari_host_is_mod_galaxy(const char* galaxy) {
    PetariNative::HostAllocationScope host;
    return galaxy != nullptr && PetariNative::App::Host::isModGalaxy(galaxy);
}

// The original galaxy whose sounds and music a mod galaxy uses: "<Galaxy>.sound=<Original>" in
// its mod's mod.txt; Sweet Sweet Galaxy's without one. nullptr for any other stage.
extern "C" const char* petari_host_mod_galaxy_sound_stage(const char* galaxy) {
    PetariNative::HostAllocationScope host;
    static std::map<std::string, std::string> chosen;
    if (galaxy == nullptr || !PetariNative::App::Host::isModGalaxy(galaxy)) return nullptr;
    auto found = chosen.find(galaxy);
    if (found == chosen.end()) {
        std::string stage = "BeltConveyerExGalaxy";
        const std::string key = std::string(galaxy) + ".sound=";
        for (const auto& root : PetariNative::App::Host::enabledModRoots()) {
            std::ifstream in(root / "mod.txt");
            std::string line;
            bool set = false;
            while (std::getline(in, line)) {
                if (!line.empty() && line.back() == '\r') line.pop_back();
                if (line.rfind(key, 0) == 0) {
                    stage = line.substr(key.size());
                    set = true;
                }
            }
            if (set) break;
        }
        found = chosen.emplace(galaxy, stage).first;
    }
    return found->second.c_str();
}

extern "C" bool petari_host_mod_progress_load(const char* slot, const char* galaxy, uint8_t* stars, uint8_t* visited, uint16_t* coins) {
    PetariNative::HostAllocationScope host;
    const auto progress = PetariNative::App::Host::readProgress(slot);
    const auto found = progress.find(galaxy);
    if (found == progress.end()) return false;
    *stars = static_cast<uint8_t>(found->second.stars);
    *visited = static_cast<uint8_t>(found->second.visited);
    for (int i = 0; i < 8; i++) coins[i] = static_cast<uint16_t>(found->second.coins[i]);
    return true;
}

extern "C" void petari_host_mod_progress_clear(const char* slot) {
    PetariNative::HostAllocationScope host;
    std::error_code ec;
    std::filesystem::remove(PetariNative::App::Host::progressFile(slot), ec);
}

extern "C" void petari_host_mod_progress_copy(const char* dstSlot, const char* srcSlot) {
    PetariNative::HostAllocationScope host;
    namespace Host = PetariNative::App::Host;
    std::error_code ec;
    std::filesystem::remove(Host::progressFile(dstSlot), ec);
    if (std::filesystem::exists(Host::progressFile(srcSlot), ec)) {
        std::filesystem::copy_file(Host::progressFile(srcSlot), Host::progressFile(dstSlot), ec);
    }
}

extern "C" void petari_host_mod_progress_save(const char* slot, const char* galaxy, uint8_t stars, uint8_t visited, const uint16_t* coins) {
    PetariNative::HostAllocationScope host;
    namespace Host = PetariNative::App::Host;
    auto progress = Host::readProgress(slot);
    auto& entry = progress[galaxy];
    entry.stars = stars;
    entry.visited = visited;
    for (int i = 0; i < 8; i++) entry.coins[i] = coins[i];
    const std::filesystem::path file = Host::progressFile(slot);
    std::error_code ec;
    std::filesystem::create_directories(file.parent_path(), ec);
    const std::filesystem::path temporary = file.string() + ".writing";
    {
        std::ofstream out(temporary, std::ios::trunc);
        out << "# Progress in galaxies that mods add (native/CUSTOM_GALAXY.md); not part of GameData.bin.\n";
        for (const auto& [name, value] : progress) {
            out << name << " stars=" << value.stars << " visited=" << value.visited << " coins=";
            for (int i = 0; i < 8; i++) out << (i ? "," : "") << value.coins[i];
            out << "\n";
        }
    }
    std::filesystem::rename(temporary, file, ec);
    if (ec) std::fprintf(stderr, "[mods] cannot write %s: %s\n", file.string().c_str(), ec.message().c_str());
}


// Text of the enabled mods for the game's messages (MessageHolder.cpp, native/CUSTOM_GALAXY.md):
// per mod, messages.<language>.txt then messages.txt, mods in precedence order, so the first line
// for an ID wins. Built once; the game keeps the pointer.
extern "C" const char* petari_host_mod_messages(const char* language) {
    PetariNative::HostAllocationScope host;
    static std::string text;
    static bool built = false;
    if (!built) {
        built = true;
        for (const auto& root : PetariNative::App::Host::enabledModRoots()) {
            for (const std::string& name : {language ? std::string("messages.") + language + ".txt" : std::string(), std::string("messages.txt")}) {
                if (name.empty()) continue;
                std::ifstream in(root / name, std::ios::binary);
                if (!in) continue;
                std::ostringstream content;
                content << in.rdbuf();
                text += content.str();
                text += "\n";
                std::fprintf(stderr, "[mods] messages from %s\n", (root / name).string().c_str());
            }
        }
    }
    return text.c_str();
}

namespace PetariNative::App::Host {

bool preparePlatform(const Paths& paths, std::string* error) {
    const std::filesystem::path crashes = paths.user / "Crashes";
    const std::filesystem::path nand = paths.user / "NAND";
    std::error_code ec;
    std::filesystem::create_directories(crashes, ec);
    if (!ec) {
        std::filesystem::create_directories(nand, ec);
    }
    if (ec) {
        *error = "cannot create " + paths.user.string() + ": " + ec.message();
        return false;
    }
    Platform::Crash::install(crashes);
    Smoke::setHangReport(dumpHangState, crashes.string());

    // Disc-file mods (native/MODS.md): none unless the player enabled one, in which
    // case the disc is unchanged for every file the mods do not supply.
    Platform::DVD::MountOptions mountOptions{paths.disc};
    {
        auto resolved = Platform::ModFolder::resolveForUser(paths.user);
        for (const std::string& line : resolved.log) std::fprintf(stderr, "[mods] %s\n", line.c_str());
        gModPaths.clear();
        for (const auto& file : resolved.files) gModPaths.insert(lower(file.path));
        gDiscRoot = paths.disc;
        gUserRoot = paths.user;
        mountOptions.overlay = std::move(resolved.files);
        rememberEnabledMods();
        namespace Mods = PetariNative::ModGalaxies;
        Mods::messages = petari_host_mod_messages;
        Mods::isModGalaxy = petari_host_is_mod_galaxy;
        Mods::isModObject = [](const char* name) {
            PetariNative::HostAllocationScope host;
            return name != nullptr && PetariNative::App::Host::isModObject(name);
        };
        Mods::soundStage = petari_host_mod_galaxy_sound_stage;
        Mods::loadProgress = petari_host_mod_progress_load;
        Mods::saveProgress = petari_host_mod_progress_save;
        Mods::clearProgress = petari_host_mod_progress_clear;
        Mods::copyProgress = petari_host_mod_progress_copy;
    }
    if (!Platform::DVD::mount(mountOptions, error)) {
        *error = "disc " + paths.disc.string() + ": " + *error;
        return false;
    }
    if (!Platform::NAND::mount(nand, error)) {
        *error = "save data " + nand.string() + ": " + *error;
        return false;
    }
    // Before OSInit, which runs SCInit.
    if (!Platform::SC::setStore(paths.user / "settings.txt", error)) {
        *error = "settings: " + *error;
        return false;
    }
    return true;
}

void startOS() {
    OSInit();
    // The SDK's play-record startup initializes NAND on Wii. The native app
    // initializes it explicitly, after DVD has made the disc ID available.
    DVDInit();
    const s32 nandResult = NANDInit();
    if (nandResult != NAND_RESULT_OK) {
        OSPanic(__FILE__, __LINE__, "Native save storage initialization failed (%d)", nandResult);
    }
    // Retraces come from the VI thread at the mode's field rate. The game
    // waits for retraces during start-up and exit, when no frame seam runs.
    // The frame seam's host work (presenting, window events) runs with the CPU
    // released, so audio, loaders and DrawSyncManager keep running.
    App::setCpuRelease({petari_os_begin_host_blocking, petari_os_end_host_blocking});
    Platform::VI::setClock(Platform::VI::Clock::Internal);
    petari_attach_vi_renderer();
    // The window shows the XFB VI latched, with VI black and dimming.
    petari_present_install();
    Platform::Power::setExitHandler(leave, nullptr);
    AudioSDL::install();
}

void runGame() {
    petari_game_main();
    std::fputs("Petari: the game's main loop returned\n", stderr);
    std::abort();
}

void requestQuit() {
    Platform::Power::pressPowerButton();
}

void forceQuit() {
    Seam::reportFrameStats();
    petari_platform_report_diagnostics();
    std::fputs("Petari: quitting immediately\n", stderr);
    std::fflush(stderr);
    std::_Exit(0);
}

}  // namespace PetariNative::App::Host

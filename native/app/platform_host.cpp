// Platform start-up and exit for the native application. SDK side: no Aurora
// or SDL headers here.

#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <sstream>
#include <system_error>
#include <revolution/dvd.h>
#include <revolution/nand.h>

#include <petari/audio_sdl.hpp>
#include <petari/boot.hpp>
#include <petari/platform/crash.hpp>
#include <petari/platform/diagnostics.hpp>
#include <petari/editor/patch.hpp>
#include <petari/platform/dvd.hpp>
#include <petari/platform/mod_folder.hpp>
#include <petari/platform/mod_galaxy.hpp>
#include <petari/platform/nand.hpp>
#include <petari/platform/os_host.hpp>
#include <petari/platform/power.hpp>
#include <petari/platform/sc.hpp>
#include <petari/platform/vi.hpp>
#include <petari/host_allocation.hpp>
#include <petari/pause_log.h>
#include <petari/mod_galaxies.hpp>

#include "host.hpp"
#include "smoke.hpp"

extern "C" void petari_game_main(void);          // src/Game/System/GameSystem.cpp
extern "C" void petari_attach_vi_renderer(void);  // native/gx/vi_bridge.cpp
extern "C" void petari_present_install(void);     // native/gx/present/present_host.cpp
extern "C" bool petari_gx_waiting_for_pipeline();  // native/gx/patch_aurora_pipeline.py

// The user directory, for the pause log (set by preparePlatform).
static std::filesystem::path gPauseLogRoot;

// A refused pause press (pause_log.h). The file stays small: past 256 KiB it starts over.
extern "C" void petari_host_pause_log(const char* line) {
    PetariNative::HostAllocationScope host;
    std::fprintf(stderr, "[pause] %s\n", line);
    const std::filesystem::path& root = gPauseLogRoot;
    if (root.empty()) return;
    const std::filesystem::path file = root / "pause-log.txt";
    std::error_code ec;
    const bool restart = std::filesystem::file_size(file, ec) > 256 * 1024 && !ec;
    std::ofstream out(file, restart ? std::ios::trunc : std::ios::app);
    if (!out) return;
    const std::time_t now = std::time(nullptr);
    char stamp[32];
    std::strftime(stamp, sizeof(stamp), "%Y-%m-%d %H:%M:%S", std::localtime(&now));
    out << stamp << "  " << line << "\n";
}

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

// Enabled folder mods in precedence order, for their messages.txt (native/CUSTOM_GALAXY.md).
std::vector<std::filesystem::path> gEnabledModRoots;

// Text of the enabled mods for the game's messages (MessageHolder.cpp): per mod, messages.<language>.txt
// then messages.txt, mods in precedence order, so the first line for an ID wins. NPC lines and other
// text the disc lacks; galaxy and mission names come from galaxy.json. Built once; the game keeps
// the pointer.
const char* modMessages(const char* language) {
    PetariNative::HostAllocationScope host;
    static std::string text;
    static bool built = false;
    if (!built) {
        built = true;
        for (const auto& root : gEnabledModRoots) {
            for (const std::string& name : {language ? std::string("messages.") + language + ".txt" : std::string(),
                                            std::string("messages.txt")}) {
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

}  // namespace

bool preparePlatform(const Paths& paths, std::string* error) {
    gPauseLogRoot = paths.user;
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
        // Level editor patch mods are built from this disc at start-up (docs/dev/level-editor/TECH.md 5.1).
        // Generated files (terrain) come from builders registered with PetariEditor::Patch::registerAssetBuilder
        // before this point (app_main: the terrain builder, unless the level editor is on).
        Platform::ModFolder::setPatchBuilder(&PetariEditor::Patch::buildForLoader);
        auto resolved = Platform::ModFolder::resolveForUser(paths.user, paths.disc);
        for (const std::string& line : resolved.log) std::fprintf(stderr, "[mods] %s\n", line.c_str());
        mountOptions.overlay = std::move(resolved.files);
        // Mod galaxies' progress is saved beside the save, never in it (TECH.md 5.7).
        Platform::ModGalaxy::setSaveDirectory(paths.user / "mods-saves");
        // New galaxies of the enabled mods (galaxy.json; docs/dev/level-editor/TECH.md 5.7), unless
        // --stage loaded them already.
        if (Platform::ModGalaxy::all().empty()) {
            std::vector<std::string> galaxyLog;
            Platform::ModGalaxy::load(Platform::ModFolder::enabledRoots(paths.user), &galaxyLog);
            for (const std::string& line : galaxyLog) std::fprintf(stderr, "[mods] %s\n", line.c_str());
        }
        gEnabledModRoots = Platform::ModFolder::enabledRoots(paths.user);
        PetariNative::ModGalaxies::messages = modMessages;
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

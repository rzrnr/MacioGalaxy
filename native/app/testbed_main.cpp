// Level testbed entry point (petari_testbed, "Galaxy Testbed.app"; native/blender/README.md).
//
// One galaxy with the game's own scene, objects, collision, camera and controls, and
// nothing in front of it: no strap screen, title, file select or observatory
// (petari/testbed.hpp). The save is a fresh file held in memory, in a throwaway user
// folder; the player's folder is only read (settings, controls, mods). A local socket
// reloads the edited zones and restarts the mission in-process, through the game's
// own stage change (the Level Select's warp).

#include <aurora/aurora.h>
#include <aurora/main.h>
#include <aurora/event.h>

#include <SDL3/SDL_events.h>
#include <SDL3/SDL_hints.h>
#include <SDL3/SDL_init.h>
#include <SDL3/SDL_video.h>
#include <objc/message.h>
#include <objc/runtime.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <cctype>
#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>

#include <petari/camera_settings.hpp>
#include <petari/cheats.hpp>
#include <petari/display_mode.hpp>
#include <petari/graphics.hpp>
#include <petari/host_allocation.hpp>
#include <petari/launch_stage.hpp>
#include <petari/mods.hpp>
#include <petari/pipeline_startup.hpp>
#include <petari/platform/crash.hpp>
#include <petari/platform/dvd.hpp>
#include <petari/platform/mod_folder.hpp>
#include <petari/player_launch.hpp>
#include <petari/test_fixture.hpp>
#include <petari/testbed.hpp>
#include <petari/volume.hpp>

#include "host.hpp"
#include "pipeline_cache_dir.hpp"
#include "smoke_background.hpp"

extern "C" void petari_gx_pipeline_background_begin();
extern "C" void petari_gx_pipeline_set_gameplay(bool gameplay);

namespace App = PetariNative::App;
namespace Smoke = PetariNative::App::Smoke;
namespace fs = std::filesystem;

namespace {

using Clock = std::chrono::steady_clock;
const Clock::time_point gLaunch = Clock::now();

double secondsSince(Clock::time_point start) {
    return std::chrono::duration<double>(Clock::now() - start).count();
}

void logMessage(AuroraLogLevel level, const char* module, const char* message, unsigned int length) {
    std::fprintf(stderr, "[%s] %.*s\n", module, static_cast<int>(length), message);
    if (level == LOG_FATAL) {
        PetariNative::Platform::Crash::recordFatalMessage(module, message, length);
        std::abort();
    }
}

void usage() {
    std::fputs("Usage: petari_testbed --stage GALAXY [--scenario N] [--spawn X,Y,Z|name:POS] [--disc DIR]\n"
               "                      [--player-user DIR] [--user DIR] [--control SOCKET] [--opening]\n"
               "                      [--background]\n"
               "  --stage GALAXY  internal name (EggStarGalaxy) or alias (good-egg); --scenario: mission, default 1\n"
               "  --spawn         Mario's start once the mission is playable (again after every reload);\n"
               "                  default: the mission's own start\n"
               "  --disc DIR      extracted disc; default $PETARI_GAME_DIR\n"
               "  --player-user   the player's folder, only read: settings, controls, mods.txt and mods/;\n"
               "                  default ~/Library/Application Support/Petari\n"
               "  --user DIR      the testbed's own folder (save, crash reports); its save is wiped at every\n"
               "                  start; default ~/Library/Caches/Petari/Testbed\n"
               "  --control SOCK  local socket for commands (reload, spawn, status, actors, quit); default <user>/control.sock\n"
               "  --opening       play the mission's opening camera flight (skipped by default)\n"
               "  --background    hidden, unfocused window with physical input ignored (automated runs)\n"
               "Mods: the player's mods.txt, or PETARI_MOD_FOLDERS=A,B for this run.\n",
               stderr);
}

struct Spawn {
    bool set = false;
    std::string name;  // a GeneralPos, else the point below
    float x = 0.0f, y = 0.0f, z = 0.0f;
};

// "x,y,z", "name:<GeneralPos>" or "none".
bool parseSpawn(const std::string& text, Spawn* spawn) {
    Spawn parsed;
    if (text == "none" || text.empty()) {
        *spawn = parsed;
        return true;
    }
    if (text.rfind("name:", 0) == 0 && text.size() > 5) {
        parsed.set = true;
        parsed.name = text.substr(5);
    } else if (std::sscanf(text.c_str(), "%f,%f,%f", &parsed.x, &parsed.y, &parsed.z) == 3) {
        parsed.set = true;
    } else {
        return false;
    }
    *spawn = parsed;
    return true;
}

std::string describe(const Spawn& spawn) {
    if (!spawn.set) return "the mission's start";
    if (!spawn.name.empty()) return "GeneralPos " + spawn.name;
    char text[96];
    std::snprintf(text, sizeof(text), "(%.0f, %.0f, %.0f)", spawn.x, spawn.y, spawn.z);
    return text;
}

// --- Shared between the control thread and the game thread ---
std::mutex gMutex;
Spawn gSpawn;            // gMutex
std::string gLastError;  // gMutex: the last failed reload
std::string gActors;     // gMutex: the observed actors of the last frame ("Kind x,y,z; ...")
std::atomic<bool> gReloadRequested{false};
std::atomic<bool> gControl{false};
std::atomic<int> gReloads{0};          // finished: control again after a reload
std::atomic<double> gLaunchSeconds{-1.0};
std::atomic<double> gReloadSeconds{-1.0};
Clock::time_point gReloadStart;        // gMutex
fs::path gUser;
fs::path gPlayer;
std::string gStage;
int gScenario = 1;

// --- Game thread only (the seam's phase probe) ---
struct GameState {
    bool reloadPending = false;   // waiting for normal play to restart the mission
    int refreshTries = 0;
    bool awaitingControl = true;  // since launch or the last restart
    bool leftStage = false;       // the restart has left the old scene
    bool spawned = false;
};
GameState gGame;

// The mod files again (sizes and positions change when the editor rewrites a zone), with
// the player's mods.txt as it is now (a first save turns the editor's mod on).
bool refreshDisc(std::string* error) {
    PetariNative::HostAllocationScope host;
    std::error_code ec;
    if (fs::is_regular_file(gPlayer / "mods.txt", ec)) {
        fs::copy_file(gPlayer / "mods.txt", gUser / "mods.txt", fs::copy_options::overwrite_existing, ec);
    }
    const auto resolved = PetariNative::Platform::ModFolder::resolveForUser(gUser);
    for (const std::string& line : resolved.log) std::fprintf(stderr, "[mods] %s\n", line.c_str());
    return PetariNative::Platform::DVD::refreshOverlay(resolved.files, error);
}

void tryRestart(const Smoke::Observation& o) {
    if (!o.pausePermitted) return;  // in a demo, talk, death or the pause menu: once it is over
    std::string error;
    if (!refreshDisc(&error)) {
        if (error == "the drive is busy" && ++gGame.refreshTries < 600) return;  // next frame
        std::fprintf(stderr, "PETARI TESTBED: reload failed: %s\n", error.c_str());
        std::lock_guard<std::mutex> lock(gMutex);
        gLastError = error;
        gGame.reloadPending = false;
        return;
    }
    gGame.reloadPending = false;
    gGame.refreshTries = 0;
    gGame.awaitingControl = true;
    gGame.leftStage = false;
    gGame.spawned = false;
    gControl.store(false);
    PetariNative::Testbed::dropFileCache.store(true);
    std::snprintf(PetariNative::PlayerLaunch::warpStage, sizeof(PetariNative::PlayerLaunch::warpStage), "%s", gStage.c_str());
    PetariNative::PlayerLaunch::warpScenario = gScenario;
    PetariNative::PlayerLaunch::warpPending.store(true);
    std::fprintf(stderr, "PETARI TESTBED: reload: disc refreshed, restarting %s mission %d\n", gStage.c_str(), gScenario);
}

App::FrameStats::Phase testbedFrame() {
    const App::FrameStats::Phase phase = App::Host::framePhase();
    const bool gameplay = phase == App::FrameStats::Phase::Gameplay && !App::Host::pauseMenuActive();
    petari_gx_pipeline_set_gameplay(gameplay);

    const Smoke::Observation o = Smoke::observeGame(true);
    const bool inStage = o.scene == "Game" && o.sceneReady && o.stage == gStage;
    const bool control = inStage && o.playerValid && o.pausePermitted && !o.demoActive && !o.playerOffControl && !o.playerDead;

    if (gReloadRequested.exchange(false)) {
        gGame.reloadPending = true;
        gGame.refreshTries = 0;
    }
    if (gGame.reloadPending && inStage) tryRestart(o);

    if (gGame.awaitingControl && !inStage) gGame.leftStage = true;
    // PETARI_TESTBED_TRACE=1: what holds Mario while the mission starts, twice a second.
    static const bool trace = std::getenv("PETARI_TESTBED_TRACE") != nullptr;
    static unsigned long traceFrames = 0;
    if (trace && gGame.awaitingControl && inStage && ++traceFrames % 30 == 0) {
        std::fprintf(stderr, "PETARI TESTBED: waiting: player %d, pause permitted %d, demo %d, control off %d, dead %d, "
                     "status %d, at (%.0f, %.0f, %.0f)\n", o.playerValid, o.pausePermitted, o.demoActive, o.playerOffControl,
                     o.playerDead, o.marioStatus, o.playerX, o.playerY, o.playerZ);
    }
    if (gGame.awaitingControl && control && gGame.leftStage) {
        gGame.awaitingControl = false;
        gControl.store(true);
        if (gLaunchSeconds.load() < 0.0) {
            gLaunchSeconds.store(secondsSince(gLaunch));
            std::fprintf(stderr, "PETARI TESTBED: control %.2f s after launch (%s mission %d), Mario at (%.0f, %.0f, %.0f)\n",
                         gLaunchSeconds.load(), gStage.c_str(), gScenario, o.playerX, o.playerY, o.playerZ);
        } else {
            Clock::time_point start;
            {
                std::lock_guard<std::mutex> lock(gMutex);
                start = gReloadStart;
            }
            gReloadSeconds.store(secondsSince(start));
            gReloads.fetch_add(1);
            std::fprintf(stderr, "PETARI TESTBED: reload %d: control %.2f s after the request, Mario at (%.0f, %.0f, %.0f)\n",
                         gReloads.load(), gReloadSeconds.load(), o.playerX, o.playerY, o.playerZ);
        }
    }
    if (!gGame.awaitingControl && !gGame.spawned && control) {
        gGame.spawned = true;
        Spawn spawn;
        {
            std::lock_guard<std::mutex> lock(gMutex);
            spawn = gSpawn;
        }
        if (spawn.set) {
            Smoke::Step step;
            step.warp = true;
            step.warpName = spawn.name;
            step.warpX = spawn.x;
            step.warpY = spawn.y;
            step.warpZ = spawn.z;
            const bool moved = Smoke::warpPlayer(step);
            std::fprintf(stderr, "PETARI TESTBED: spawn at %s%s (from %.0f, %.0f, %.0f)\n", describe(spawn).c_str(),
                         moved ? "" : " failed: no player", o.playerX, o.playerY, o.playerZ);
        }
    }
    if (gControl.load() && !inStage) gControl.store(false);
    // Kept for the actors command, at most twice a second.
    static unsigned long actorFrames = 0;
    if (++actorFrames % 30 == 0) {
        std::string actors;
        for (const Smoke::Observation::Actor& actor : o.actors) {
            char text[96];
            std::snprintf(text, sizeof(text), "%s%s %.0f,%.0f,%.0f", actors.empty() ? "" : "; ", actor.kind.c_str(), actor.x,
                          actor.y, actor.z);
            actors += text;
        }
        std::lock_guard<std::mutex> lock(gMutex);
        gActors = std::move(actors);
    }
    return phase;
}

// --- The control socket: one command per connection, one line back ---
std::string handleCommand(const std::string& line) {
    std::string command = line, argument;
    if (const auto space = line.find(' '); space != std::string::npos) {
        command = line.substr(0, space);
        argument = line.substr(space + 1);
    }
    if (command == "reload" || command == "spawn") {
        if (!argument.empty() || command == "spawn") {
            Spawn spawn;
            if (!parseSpawn(argument, &spawn)) return "error: spawn expects x,y,z, name:<GeneralPos> or none";
            std::lock_guard<std::mutex> lock(gMutex);
            gSpawn = spawn;
        }
        if (command == "spawn") {
            std::lock_guard<std::mutex> lock(gMutex);
            return "ok spawn " + describe(gSpawn) + " (from the next restart)";
        }
        {
            std::lock_guard<std::mutex> lock(gMutex);
            gReloadStart = Clock::now();
            gLastError.clear();
        }
        gReloadRequested.store(true);
        return "ok reload queued";
    }
    if (command == "status") {
        std::lock_guard<std::mutex> lock(gMutex);
        char text[512];
        std::snprintf(text, sizeof(text), "ok stage=%s scenario=%d control=%d reloads=%d launch=%.2f reload=%.2f pid=%d%s%s",
                      gStage.c_str(), gScenario, gControl.load() ? 1 : 0, gReloads.load(), gLaunchSeconds.load(),
                      gReloadSeconds.load(), static_cast<int>(getpid()), gLastError.empty() ? "" : " error=",
                      gLastError.c_str());
        return text;
    }
    if (command == "actors") {  // the game's observed actors (petari/actor_observe.hpp; PETARI_OBSERVE=1), for tests
        std::lock_guard<std::mutex> lock(gMutex);
        return "ok " + gActors;
    }
    if (command == "quit") {
        SDL_Event event{};
        event.type = SDL_EVENT_QUIT;
        SDL_PushEvent(&event);
        return "ok quitting";
    }
    return "error: unknown command (reload [spawn], spawn X,Y,Z|name:POS|none, status, actors, quit)";
}

void serveControl(int listener) {
    PetariNative::HostAllocationScope host;
    while (true) {
        const int client = ::accept(listener, nullptr, nullptr);
        if (client < 0) {
            if (errno == EINTR) continue;
            return;
        }
        std::string line;
        char c = 0;
        while (line.size() < 512 && ::read(client, &c, 1) == 1 && c != '\n') line += c;
        while (!line.empty() && (line.back() == '\r' || line.back() == ' ')) line.pop_back();
        const std::string reply = handleCommand(line) + "\n";
        if (line != "status" && line != "actors") std::fprintf(stderr, "PETARI TESTBED: control \"%s\": %s", line.c_str(), reply.c_str());
        (void)!::write(client, reply.data(), reply.size());
        ::close(client);
    }
}

bool startControl(const fs::path& path) {
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    if (path.string().size() >= sizeof(address.sun_path)) {
        std::fprintf(stderr, "petari_testbed: control socket path too long: %s\n", path.c_str());
        return false;
    }
    std::snprintf(address.sun_path, sizeof(address.sun_path), "%s", path.c_str());
    // A socket left by an earlier testbed: refuse if one still answers.
    const int probe = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (probe >= 0 && ::connect(probe, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0) {
        ::close(probe);
        std::fprintf(stderr, "petari_testbed: another testbed answers on %s\n", path.c_str());
        return false;
    }
    if (probe >= 0) ::close(probe);
    ::unlink(path.c_str());
    const int listener = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (listener < 0 || ::bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0 ||
        ::listen(listener, 4) != 0) {
        std::fprintf(stderr, "petari_testbed: cannot listen on %s: %s\n", path.c_str(), std::strerror(errno));
        if (listener >= 0) ::close(listener);
        return false;
    }
    std::thread(serveControl, listener).detach();
    std::fprintf(stderr, "PETARI TESTBED: control socket %s\n", path.c_str());
    return true;
}

// The testbed's folder: settings copied from the player's (read only), the player's mods
// linked, and no save (the game then sets up its file in memory).
bool prepareUser(const fs::path& user, const fs::path& player, std::string* error) {
    std::error_code ec;
    fs::create_directories(user, ec);
    if (ec) {
        *error = "cannot create " + user.string() + ": " + ec.message();
        return false;
    }
    if (fs::weakly_canonical(user, ec) == fs::weakly_canonical(player, ec)) {
        *error = "--user must not be the player's folder";
        return false;
    }
    for (const char* stale : {"NAND", "ModProgress"}) fs::remove_all(user / stale, ec);
    for (const char* name : {"controls.txt", "mods.txt", "camera.txt", "cheats.txt", "sound.txt", "graphics.txt"}) {
        fs::remove(user / name, ec);
        if (fs::is_regular_file(player / name, ec)) fs::copy_file(player / name, user / name, ec);
    }
    const fs::path mods = user / "mods";
    if (fs::is_symlink(fs::symlink_status(mods, ec))) {
        fs::remove(mods, ec);
    } else if (fs::exists(fs::symlink_status(mods, ec))) {
        *error = mods.string() + " exists and is not a link to the player's mods";
        return false;
    }
    if (fs::is_directory(player / "mods", ec)) {
        fs::create_directory_symlink(player / "mods", mods, ec);
        if (ec) {
            *error = "cannot link " + mods.string() + ": " + ec.message();
            return false;
        }
    }
    return true;
}

// An alias (good-egg) or an internal name whose scenario archive is on the disc or in a mod.
bool resolveStage(const std::string& name, int scenario, const fs::path& disc, const fs::path& user, std::string* stage) {
    std::string error;
    if (App::LaunchStage::resolve(name, scenario, stage, &error)) return true;
    for (char c : name) {
        if (!std::isalnum(static_cast<unsigned char>(c))) {
            std::fprintf(stderr, "petari_testbed: %s\n", error.c_str());
            return false;
        }
    }
    const fs::path archive = fs::path("StageData") / name / (name + "Scenario.arc");
    std::error_code ec;
    bool found = fs::is_regular_file(disc / "files" / archive, ec);
    for (fs::directory_iterator it(user / "mods", ec), end; !found && !ec && it != end; it.increment(ec)) {
        found = fs::is_regular_file(it->path() / "files" / archive, ec);
    }
    if (!found) {
        std::fprintf(stderr, "petari_testbed: no galaxy %s (%s; no %s on the disc or in a mod)\n", name.c_str(),
                     error.c_str(), archive.c_str());
        return false;
    }
    *stage = name;
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    PetariNative::prepareAllocationSymbols();
    const char* home = std::getenv("HOME");
    if (home == nullptr || home[0] == '\0') {
        std::fputs("petari_testbed: HOME is not set\n", stderr);
        return 2;
    }
    App::Paths paths;
    fs::path player = fs::path(home) / "Library/Application Support/Petari";
    fs::path control;
    std::string stageName;
    bool background = false;
    for (int i = 1; i < argc; i++) {
        const std::string arg = argv[i];
        const bool hasValue = i + 1 < argc;
        if (arg == "--stage" && hasValue) {
            stageName = argv[++i];
        } else if (arg == "--scenario" && hasValue) {
            char* end = nullptr;
            const long value = std::strtol(argv[++i], &end, 10);
            if (end == argv[i] || *end != '\0' || value < 1 || value > 8) {
                std::fprintf(stderr, "petari_testbed: --scenario expects 1..8, got %s\n", argv[i]);
                return 2;
            }
            gScenario = static_cast<int>(value);
        } else if (arg == "--spawn" && hasValue) {
            if (!parseSpawn(argv[++i], &gSpawn)) {
                std::fprintf(stderr, "petari_testbed: --spawn expects x,y,z or name:<GeneralPos>, got %s\n", argv[i]);
                return 2;
            }
        } else if (arg == "--disc" && hasValue) {
            paths.disc = argv[++i];
        } else if (arg == "--player-user" && hasValue) {
            player = argv[++i];
        } else if (arg == "--user" && hasValue) {
            paths.user = argv[++i];
        } else if (arg == "--control" && hasValue) {
            control = argv[++i];
        } else if (arg == "--background") {
            background = true;
        } else if (arg == "--opening") {
            PetariNative::Testbed::skipOpeningCamera = false;
        } else {
            usage();
            return 2;
        }
    }
    if (stageName.empty()) {
        usage();
        return 2;
    }
    if (paths.disc.empty()) {
        const char* env = std::getenv("PETARI_GAME_DIR");
        if (env == nullptr || env[0] == '\0') {
            std::fputs("petari_testbed: no disc: pass --disc or set PETARI_GAME_DIR\n", stderr);
            return 2;
        }
        paths.disc = env;
    }
    if (paths.user.empty()) paths.user = fs::path(home) / "Library/Caches/Petari/Testbed";
    if (control.empty()) control = paths.user / "control.sock";

    std::string error;
    if (!prepareUser(paths.user, player, &error)) {
        std::fprintf(stderr, "petari_testbed: %s\n", error.c_str());
        return 1;
    }
    if (!resolveStage(stageName, gScenario, paths.disc, paths.user, &gStage)) return 2;
    gUser = paths.user;
    gPlayer = player;
    PetariNative::Testbed::active = true;
    PetariNative::TestFixture::stage = gStage;
    PetariNative::TestFixture::stageScenario = gScenario;
    std::fprintf(stderr, "PETARI TESTBED: %s mission %d, spawn %s; user %s (player settings from %s)\n", gStage.c_str(),
                 gScenario, describe(gSpawn).c_str(), paths.user.c_str(), player.c_str());

    if (!App::Host::preparePlatform(paths, &error)) {
        std::fprintf(stderr, "petari_testbed: %s\n", error.c_str());
        return 1;
    }
    if (!App::Events::loadControls(paths.user / "controls.txt", &error)) {
        std::fprintf(stderr, "petari_testbed: controls: %s\n", error.c_str());
        return 1;
    }
    if (!PetariNative::Mods::load(paths.user / "mods.txt", &error)) {
        std::fprintf(stderr, "petari_testbed: mods: %s\n", error.c_str());
        return 1;
    }
    if (!PetariNative::CameraSettings::load(paths.user / "camera.txt", &error)) {
        std::fprintf(stderr, "petari_testbed: camera: %s\n", error.c_str());
        return 1;
    }
    if (!PetariNative::Cheats::load(paths.user / "cheats.txt", &error)) {
        std::fprintf(stderr, "petari_testbed: cheats: %s (using the defaults)\n", error.c_str());
    }
    if (!PetariNative::Volume::load(paths.user / "sound.txt", &error)) {
        std::fprintf(stderr, "petari_testbed: sound: %s\n", error.c_str());
    }
    if (!PetariNative::Graphics::load(paths.user / "graphics.txt", &error)) {
        std::fprintf(stderr, "petari_testbed: graphics: %s (using the defaults)\n", error.c_str());
    }
    if (!startControl(control)) return 1;

    App::SmokeBackground::enabled = background;
    SDL_SetHintWithPriority("PETARI_SMOKE_BACKGROUND", background ? "1" : "0", SDL_HINT_OVERRIDE);
    if (background) {
        // As the background smoke run (app_main.cpp): accessory app, hidden window, no physical input.
        SDL_SetHintWithPriority(SDL_HINT_MAC_BACKGROUND_APP, "1", SDL_HINT_OVERRIDE);
        SDL_SetHintWithPriority(SDL_HINT_WINDOW_ACTIVATE_WHEN_SHOWN, "0", SDL_HINT_OVERRIDE);
        SDL_SetHintWithPriority(SDL_HINT_WINDOW_ACTIVATE_WHEN_RAISED, "0", SDL_HINT_OVERRIDE);
        SDL_SetEventFilter(App::SmokeBackground::eventFilter, nullptr);
        if (!SDL_InitSubSystem(SDL_INIT_VIDEO)) {
            std::fprintf(stderr, "petari_testbed: background video initialization: %s\n", SDL_GetError());
            return 1;
        }
        const auto sendObject = reinterpret_cast<id (*)(id, SEL)>(objc_msgSend);
        const id application = sendObject(reinterpret_cast<id>(objc_getClass("NSApplication")), sel_registerName("sharedApplication"));
        const auto setPolicy = reinterpret_cast<BOOL (*)(id, SEL, long)>(objc_msgSend);
        if (!application || !setPolicy(application, sel_registerName("setActivationPolicy:"), 1 /* Accessory */)) {
            std::fputs("petari_testbed: could not set background app activation policy\n", stderr);
            return 1;
        }
    }

    const std::string userPath = paths.user.string();
    AuroraConfig config{};
    config.appName = "Galaxy Testbed";
    config.userPath = userPath.c_str();
    // The player's warm shader cache when the game is not running (it holds the lock otherwise).
    App::PipelineCacheDir pipelineCache;
    pipelineCache.prepare(paths.user, false, std::getenv("PETARI_CACHE_DIR"));
    const std::string cachePath = pipelineCache.path.string();
    config.cachePath = cachePath.c_str();
    config.desiredBackend = BACKEND_METAL;
    config.vsync = false;
    config.pauseOnFocusLost = false;
    config.windowWidth = 1280;
    config.windowHeight = 720;
    if (!background) {
        // Windowed at every start (the testbed's own display.txt; Cmd+Return switches).
        App::Display::load(paths.user / "display.txt", &error);
        App::Display::configureHints();
        config.startFullscreen = false;
    }
    config.logCallback = logMessage;
    config.logLevel = LOG_INFO;
    const AuroraInfo info = aurora_initialize(1, argv, &config);
    if (info.window == nullptr || aurora_get_backend() != BACKEND_METAL) {
        std::fputs("petari_testbed: Metal initialization failed\n", stderr);
        aurora_shutdown();
        return 1;
    }
    auto* window = static_cast<SDL_Window*>(info.window);
    if (!background) {
        App::Display::attach(window);
        const std::string title = "Galaxy Testbed: " + gStage + " " + std::to_string(gScenario);
        SDL_SetWindowTitle(window, title.c_str());
    } else {
        SDL_SetWindowFocusable(window, false);
        App::Events::assertFocus();
    }
    petari_gx_pipeline_background_begin();
    if (!SDL_InitSubSystem(SDL_INIT_AUDIO)) {
        std::fprintf(stderr, "petari_testbed: SDL audio: %s\n", SDL_GetError());
    }

    App::Seam::attach(info.window);
    App::Seam::setPhaseProbe(testbedFrame);
    App::Host::startOS();
    App::Seam::openFirstFrame();
    App::Host::runGame();
}

// The per-frame host seam (petari/app.hpp). Aurora and SDL side.

#ifdef PETARI_EDITOR_UI
#include <petari/editor/ui.hpp>
#endif
#include <petari/present_stats.hpp>
#include <aurora/aurora.h>
#include <aurora/event.h>

#include <SDL3/SDL_timer.h>
#include <SDL3/SDL_events.h>
#include <SDL3/SDL_video.h>
#include <SDL3/SDL_mouse.h>
#include <SDL3/SDL_keyboard.h>
#ifdef PETARI_EDITOR_UI
#include <imgui.h>
#include <imgui_internal.h>  // GImGui->HoveredWindow, ActiveId (the mouse trace)
#endif

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>

extern "C" uint64_t petari_gx_pipeline_manifest_failure_count();
extern "C" void petari_gx_pipeline_report();

#include "frame_stats.hpp"
#include "spike_profiler.hpp"
#include "host.hpp"
#include "progress_observe.hpp"
#include "smoke_background.hpp"
#include "smoke.hpp"
#include "route_record.hpp"
#include "smoke_domes.hpp"
#include "smoke_movement.hpp"
#include "smoke_replay.hpp"
#include <petari/agent_replay.hpp>
#include <fstream>
#include <sstream>
#include "smoke_goodegg.hpp"
#include "smoke_soak.hpp"
#include "smoke_stage.hpp"
#include "soak_telemetry.hpp"
#include "stats_overlay.hpp"
#include "petari/asset_diagnostics.hpp"
#include "petari/display_mode.hpp"
#include "petari/frame_telemetry.hpp"
#include "petari/present_pacing.hpp"
#include "petari/graphics.hpp"
#include "petari/home_menu.hpp"
#include "petari/host_allocation.hpp"
#include "petari/input.hpp"
#include "petari/latency_probe.hpp"
#include "petari/test_fixture.hpp"

namespace PetariNative::App {

namespace {

PresentHooks gPresent;
CpuRelease gRelease;
constexpr std::uint64_t kRetraceNs = 16683333;  // 59.94 Hz
std::uint64_t gStepPresentNs = 0;  // the step's aurora_end_frame, for frame interpolation's extra frame
// Input latency Reduced (petari_host_input_first): this step is computed first and drawn at once,
// so its extra frame, when there is one, is presented before the step's frame.
bool gInputFirst = false;
bool gExtraThisStep = false;           // this step's extra frame was presented
std::uint64_t gExtraPresentNs = 0;
std::uint64_t gExtraFrameNs = 4000000;  // how long an extra frame takes to draw, smoothed
std::uint64_t gExtraStartNs = 0;
std::uint64_t gExtraFrames = 0;    // frame interpolation's presents, in the frame time report
std::uint64_t gLateSteps = 0;      // steps without an extra frame: presented too late
std::uint64_t gSlowDisplaySteps = 0;  // or on a display below 100 Hz
int gDisplayHz = 0;                // the window's display, checked once a second; 0: unknown
// The last second's steps that asked for an extra frame, for Graphics::setFrameRateStatus.
struct InterpolationSecond {
    std::uint64_t start = 0;
    unsigned asked = 0;
    unsigned drawn = 0;
    unsigned late = 0;
};
InterpolationSecond gInterpolationSecond;

SDL_Window* gWindow = nullptr;
int gQuitRequests = 0;
Rect gLastImage;
float gLastWindowWidth = -1.0f;
float gLastWindowHeight = -1.0f;
bool gWarnedImageRect = false;

// Once a second: the window's display (it can move to another one) and how many of the last
// second's steps got an extra frame, for the Graphics page and the stats.
void publishFrameRateStatus(std::uint64_t now) {
    InterpolationSecond& second = gInterpolationSecond;
    if (second.start != 0 && now - second.start < 1000000000ull) {
        return;
    }
    if (gWindow != nullptr) {
        const SDL_DisplayMode* mode = SDL_GetCurrentDisplayMode(SDL_GetDisplayForWindow(gWindow));
        gDisplayHz = mode != nullptr && mode->refresh_rate > 0.0f ? static_cast<int>(std::lround(mode->refresh_rate)) : 0;
    }
    PetariNative::Graphics::FrameRateStatus status;
    status.displayHz = gDisplayHz;
    if (second.asked > 0) {
        status.interpolatedPercent = static_cast<int>(second.drawn * 100 / second.asked);
        status.latePercent = static_cast<int>(second.late * 100 / second.asked);
    }
    PetariNative::Graphics::setFrameRateStatus(status);
    second = InterpolationSecond{};
    second.start = now;
}

// Input that came since the seam's event pump is handed to the game before it reads its
// controllers (takeInputEarly); the seam's own pump then skips those events for the game.
std::uint64_t gEarlyInputNs = 0;  // the newest input event handed over early

bool inputEvent(Uint32 type) {
    return (type >= SDL_EVENT_KEY_DOWN && type <= SDL_EVENT_MOUSE_WHEEL) ||
           (type >= SDL_EVENT_GAMEPAD_AXIS_MOTION && type <= SDL_EVENT_GAMEPAD_BUTTON_UP);
}

// Opt-in start-up telemetry (PETARI_TRACE_BOOT=1): the first frame that
// reaches the seam, then one line every kTraceInterval frames. Observation only.
constexpr unsigned kTraceInterval = 120;
using TraceClock = std::chrono::steady_clock;
struct Trace {
    bool enabled = false;
    unsigned long frames = 0;
    unsigned long lastFrames = 0;
    unsigned long unpresentableWaits = 0;  // failed aurora_begin_frame calls
    TraceClock::time_point start;
    TraceClock::time_point last;
    TraceClock::time_point previousFrame;
    double maxFrameMs = 0.0;
    unsigned slowFrames = 0;
};
Trace gTrace;

// Frame-time statistics (frame_stats.hpp): always collected, printed at exit
// with PETARI_TRACE_BOOT or PETARI_FRAME_STATS, per-frame rows written to
// PETARI_FRAME_CSV. Everything here runs on the game (main) thread.
namespace Telemetry = PetariNative::FrameTelemetry;
unsigned long environmentNumber(const char* name, unsigned long fallback);
struct Timing {
    FrameStats::Recorder* recorder = nullptr;
    FrameStats::Phase (*probe)() = nullptr;
    bool report = false;
    const char* csvPath = nullptr;
    double spikeMs = 1000.0 / 30.0;  // PETARI_SPIKE_PROFILE_MS
    std::uint64_t frames = 0;
    std::uint64_t lastEntry = 0;  // previous seam entry, 0 before the first
    std::uint64_t lastExit = 0;
    std::uint64_t seamNs[4] = {};  // previous seam: compose, end frame, begin frame, reacquire
    std::uint64_t retraceDone = 0;  // frame loop marks, this frame
    std::uint64_t retraceWake = 0;
    std::uint64_t endFrame = 0;
    bool unfocused = false;        // window focus, from events
    bool unfocusedInFrame = false; // unfocused or unpresentable at any time this frame
    std::uint64_t counterNs[Telemetry::CounterCount] = {};
    std::uint64_t counterEvents[Telemetry::CounterCount] = {};
};
Timing gTiming;

std::uint32_t microseconds(std::uint64_t ns) {
    const std::uint64_t us = ns / 1000;
    return us > 0xffffffffu ? 0xffffffffu : static_cast<std::uint32_t>(us);
}

// Since the previous call: time and events of a cross-thread counter.
std::uint64_t takeCounter(Telemetry::Counter counter, std::uint64_t* events = nullptr) {
    const std::uint64_t ns = Telemetry::slots[counter].ns.load(std::memory_order_relaxed);
    const std::uint64_t count = Telemetry::slots[counter].events.load(std::memory_order_relaxed);
    const std::uint64_t delta = ns - gTiming.counterNs[counter];
    if (events != nullptr) {
        *events = count - gTiming.counterEvents[counter];
    }
    gTiming.counterNs[counter] = ns;
    gTiming.counterEvents[counter] = count;
    return delta;
}

std::uint64_t takeMax(Telemetry::Counter counter) {
    return Telemetry::slots[counter].maxNs.exchange(0, std::memory_order_relaxed);
}

// At a seam entry: the frame since the previous seam entry.
void recordFrame(std::uint64_t entry, FrameStats::Phase phase) {
    Timing& t = gTiming;
    if (t.recorder == nullptr) {
        return;
    }
    if (t.lastEntry == 0) {
        for (unsigned counter = 0; counter < Telemetry::CounterCount; counter++) {
            takeCounter(static_cast<Telemetry::Counter>(counter));
            takeMax(static_cast<Telemetry::Counter>(counter));
        }
        t.lastEntry = entry;
        return;
    }
    FrameStats::Frame frame;
    frame.index = ++t.frames;
    frame.entryNs = entry;
    frame.intervalMs = static_cast<double>(entry - t.lastEntry) / 1e6;
    frame.phase = phase;
    frame.unfocused = t.unfocusedInFrame;
    frame.us[FrameStats::SeamCompose] = microseconds(t.seamNs[0]);
    frame.us[FrameStats::SeamEndFrame] = microseconds(t.seamNs[1]);
    frame.us[FrameStats::SeamBeginFrame] = microseconds(t.seamNs[2]);
    frame.us[FrameStats::SeamReacquire] = microseconds(t.seamNs[3]);
    // The frame loop's marks, if they fall in order inside this frame.
    const bool retrace = t.retraceDone >= t.lastExit && t.retraceDone <= entry && t.lastExit != 0;
    const std::uint64_t workStart = retrace ? t.retraceDone : t.lastExit;
    const bool endFrame = t.endFrame >= workStart && t.endFrame <= entry && t.lastExit != 0;
    if (retrace) {
        frame.us[FrameStats::RetraceWait] = microseconds(t.retraceDone - t.lastExit);
        frame.us[FrameStats::RetraceWake] = microseconds(t.retraceWake);
    }
    if (retrace && endFrame) {
        frame.us[FrameStats::GameWork] = microseconds(t.endFrame - t.retraceDone);
    }
    if (endFrame) {
        frame.us[FrameStats::DrawDoneWait] = microseconds(entry - t.endFrame);
    }
    std::uint64_t attributed = 0;
    for (unsigned part = 0; part < FrameStats::Unattributed; part++) {
        attributed += frame.us[part];
    }
    const std::uint64_t intervalUs = (entry - t.lastEntry) / 1000;
    frame.us[FrameStats::Unattributed] = microseconds(intervalUs > attributed ? (intervalUs - attributed) * 1000 : 0);

    std::uint64_t events = 0;
    frame.us[FrameStats::PipelineWait] = microseconds(takeCounter(Telemetry::PipelineWait, &events));
    frame.pipelineWaits = static_cast<std::uint32_t>(events);
    frame.us[FrameStats::EfbStagingWait] = microseconds(takeCounter(Telemetry::EfbStagingWait));
    frame.us[FrameStats::EfbSubmitWait] = microseconds(takeCounter(Telemetry::EfbSubmitWait, &events));
    frame.efbCaptures = static_cast<std::uint32_t>(events);
    takeCounter(Telemetry::EfbCaptureLatency);
    frame.us[FrameStats::EfbCaptureMax] = microseconds(takeMax(Telemetry::EfbCaptureLatency));
    frame.us[FrameStats::DrawableAcquire] = microseconds(takeCounter(Telemetry::DrawableAcquire));
    frame.us[FrameStats::FrameSubmit] = microseconds(takeCounter(Telemetry::FrameSubmit));
    frame.us[FrameStats::PresentCall] = microseconds(takeCounter(Telemetry::PresentCall));
    takeCounter(Telemetry::ViTimerLate);
    frame.us[FrameStats::ViTimerLateMax] = microseconds(takeMax(Telemetry::ViTimerLate));
    takeCounter(Telemetry::ViInterruptLockWait);
    frame.us[FrameStats::ViLockWaitMax] = microseconds(takeMax(Telemetry::ViInterruptLockWait));
    frame.us[FrameStats::TextureHash] = microseconds(takeCounter(Telemetry::TextureHash));
    frame.us[FrameStats::TextureUpload] = microseconds(takeCounter(Telemetry::TextureUpload, &events));
    frame.textureUploads = static_cast<std::uint32_t>(events);
    frame.us[FrameStats::TokenBarrierWait] = microseconds(takeCounter(Telemetry::TokenBarrierWait));
    frame.us[FrameStats::StagePrepWait] = microseconds(takeCounter(Telemetry::StagePrepWait));
    // A scene start that waited for its stage's shaders is part of loading,
    // though the scene reports itself ready by the frame's end.
    if (frame.us[FrameStats::StagePrepWait] >= 1000) {
        frame.phase = FrameStats::Phase::Loading;
    }
    t.recorder->add(frame);
    StatsOverlay::Sample overlay;
    overlay.intervalMs = frame.intervalMs;
    overlay.workMs = frame.us[FrameStats::GameWork] / 1000.0;
    overlay.drawDoneMs = frame.us[FrameStats::DrawDoneWait] / 1000.0;
    overlay.presentMs = (frame.us[FrameStats::SeamEndFrame] + frame.us[FrameStats::SeamBeginFrame]) / 1000.0;
    StatsOverlay::addFrame(overlay);
    if (frame.intervalMs > t.spikeMs && SpikeProfiler::enabled()) {
        SpikeProfiler::keepSpike(frame.index, frame.intervalMs, t.lastEntry, entry);
    }

    t.lastEntry = entry;
    t.retraceDone = t.retraceWake = t.endFrame = 0;
    t.unfocusedInFrame = t.unfocused;
}

void startTiming() {
    if (SmokeBackground::enabled) {
        gTiming.unfocused = gTiming.unfocusedInFrame = true;
    }
    const auto enabled = [](const char* name) {
        const char* value = std::getenv(name);
        return value != nullptr && value[0] != '\0' && value[0] != '0';
    };
    const char* csv = std::getenv("PETARI_FRAME_CSV");
    gTiming.csvPath = csv != nullptr && csv[0] != '\0' ? csv : nullptr;
    gTiming.report = gTiming.csvPath != nullptr || enabled("PETARI_FRAME_STATS") || enabled("PETARI_TRACE_BOOT");
    if (SpikeProfiler::startFromEnvironment()) {
        const unsigned long spikeMs = environmentNumber("PETARI_SPIKE_PROFILE_MS", 0);
        if (spikeMs > 0) {
            gTiming.spikeMs = static_cast<double>(spikeMs);
        }
    }
    if (gTiming.recorder == nullptr) {
        // 30 minutes at 60 frames/s by default, about 100 bytes per frame.
        const std::size_t csvFrames = gTiming.csvPath != nullptr ? environmentNumber("PETARI_FRAME_CSV_FRAMES", 108000) : 0;
        gTiming.recorder = new FrameStats::Recorder(csvFrames);
    }
}

// The automated smoke run (smoke.hpp), when PETARI_SMOKE selects a script.
Smoke::Driver* gSmoke = nullptr;
// Or the stage script (smoke_stage.hpp), PETARI_SMOKE=stage.
Smoke::StageDriver* gStage = nullptr;
// Or Good Egg mission 1 (smoke_goodegg.hpp), PETARI_SMOKE=goodegg1.
Smoke::GoodEggDriver* gGoodEgg = nullptr;
// Or the long-session soak (smoke_soak.hpp), PETARI_SMOKE=soak.
Smoke::SoakDriver* gSoak = nullptr;
// Or the dome tour (smoke_domes.hpp), PETARI_SMOKE=domes.
Smoke::DomesDriver* gDomes = nullptr;
Smoke::ReplayDriver* gReplay = nullptr;
Smoke::ReplayDriver* gAgentReplay = nullptr;
uint64_t gAgentMissingLayout = 0;
uint64_t gAgentMissingSound = 0;
uint64_t gAgentManifestFailures = 0;
bool gAgentAssetFailure = false;
Smoke::MovementDriver* gMovement = nullptr;

unsigned long environmentNumber(const char* name, unsigned long fallback) {
    const char* value = std::getenv(name);
    if (value == nullptr || value[0] == '\0') {
        return fallback;
    }
    char* end = nullptr;
    const unsigned long number = std::strtoul(value, &end, 10);
    return end != nullptr && *end == '\0' && number > 0 ? number : fallback;
}

void startSmoke() {
    Soak::startTelemetryFromEnvironment();  // PETARI_SOAK_CSV, with any script or none
    Smoke::SoakConfig soak;
    if (Smoke::soakEnabledFromEnvironment(&soak)) {
        if (TestFixture::stage.empty()) {
            std::fprintf(stderr, "PETARI SMOKE: soak needs --test-fixture stage (with PETARI_STAGE); not running\n");
            return;
        }
        // Only a validated stage fixture's entry is ever changed.
        soak.setStage = [](const std::string& stage, int scenario) {
            if (!TestFixture::stage.empty()) {
                TestFixture::stage = stage;
                TestFixture::stageScenario = scenario;
            }
        };
        const unsigned long frames = environmentNumber("PETARI_SMOKE_FRAMES", 20000);  // per stage cycle
        const unsigned long stall = environmentNumber("PETARI_SMOKE_STALL_SECONDS", 60);
        gSoak = new Smoke::SoakDriver(frames, soak);
        std::fprintf(stderr, "PETARI SMOKE: script soak (%zu stage(s), %.0f minutes), stage frame limit %lu, stall limit %lu s\n",
                     soak.stages.size(), soak.minutes, frames, stall);
        std::fflush(stderr);
        Smoke::startWatchdog(static_cast<unsigned>(stall), 20);
        return;
    }
    if (Smoke::movementEnabledFromEnvironment()) {
        const unsigned long frames = environmentNumber("PETARI_SMOKE_FRAMES", 36000);
        const unsigned long stall = environmentNumber("PETARI_SMOKE_STALL_SECONDS", 60);
        gMovement = new Smoke::MovementDriver(frames);
        std::fprintf(stderr, "PETARI SMOKE: script movement, frame limit %lu, stall limit %lu s\n", frames, stall);
        std::fflush(stderr);
        Smoke::startWatchdog(static_cast<unsigned>(stall), 20);
        return;
    }
    Smoke::ReplayConfig replay;
    if (Smoke::replayEnabledFromEnvironment(&replay)) {
        const unsigned long frames = environmentNumber("PETARI_SMOKE_FRAMES", 108000);
        const unsigned long stall = environmentNumber("PETARI_SMOKE_STALL_SECONDS", 60);
        gReplay = new Smoke::ReplayDriver(frames, replay);
        std::fprintf(stderr, "PETARI SMOKE: script replay (%s scenario %d, %zu route points from %s), frame limit %lu, stall limit %lu s\n",
                     replay.stage.c_str(), replay.scenario, replay.route.size(), replay.routePath.c_str(), frames, stall);
        std::fflush(stderr);
        Smoke::startWatchdog(static_cast<unsigned>(stall), 20);
        return;
    }
    Smoke::DomesConfig domes;
    if (Smoke::domesEnabledFromEnvironment(&domes)) {
        const unsigned long frames = environmentNumber("PETARI_SMOKE_FRAMES", 72000);
        const unsigned long stall = environmentNumber("PETARI_SMOKE_STALL_SECONDS", 60);
        gDomes = new Smoke::DomesDriver(frames, domes);
        std::fprintf(stderr, "PETARI SMOKE: script domes (dome %d, %zu extra mission(s)), frame limit %lu, stall limit %lu s\n",
                     domes.dome, domes.extras.size(), frames, stall);
        std::fflush(stderr);
        Smoke::startWatchdog(static_cast<unsigned>(stall), 20);
        return;
    }
    Smoke::GoodEggConfig goodEgg;
    if (Smoke::goodEggEnabledFromEnvironment(&goodEgg)) {
        const unsigned long frames = environmentNumber("PETARI_SMOKE_FRAMES", 72000);
        const unsigned long stall = environmentNumber("PETARI_SMOKE_STALL_SECONDS", 60);
        gGoodEgg = new Smoke::GoodEggDriver(frames, goodEgg);
        std::fprintf(stderr, "PETARI SMOKE: script goodegg1 (%s), frame limit %lu, stall limit %lu s\n",
                     goodEgg.synthetic ? "synthetic stage entry" : "galaxy route", frames, stall);
        std::fflush(stderr);
        Smoke::startWatchdog(static_cast<unsigned>(stall), 20);
        return;
    }
    Smoke::StageConfig stage;
    if (Smoke::stageEnabledFromEnvironment(&stage)) {
        const unsigned long frames = environmentNumber("PETARI_SMOKE_FRAMES", 12000);
        const unsigned long stall = environmentNumber("PETARI_SMOKE_STALL_SECONDS", 60);
        gStage = new Smoke::StageDriver(frames, stage);
        std::fprintf(stderr, "PETARI SMOKE: script stage (%s scenario %d, synthetic entry), frame limit %lu, stall limit %lu s\n",
                     stage.stage.c_str(), stage.scenario, frames, stall);
        std::fflush(stderr);
        Smoke::startWatchdog(static_cast<unsigned>(stall), 20);
        return;
    }
    Smoke::Script script = Smoke::Script::Title;
    if (!Smoke::enabledFromEnvironment(&script)) {
        return;
    }
    const unsigned long frames = environmentNumber("PETARI_SMOKE_FRAMES", 7200);
    const unsigned long stall = environmentNumber("PETARI_SMOKE_STALL_SECONDS", 60);
    gSmoke = new Smoke::Driver(frames, script);
    const char* scriptName = "title";
    switch (script) {
    case Smoke::Script::Title: break;
    case Smoke::Script::Playable: scriptName = "playable"; break;
    case Smoke::Script::Gameplay: scriptName = "gameplay"; break;
    case Smoke::Script::Reload: scriptName = "reload"; break;
    case Smoke::Script::Story: scriptName = "story"; break;
    case Smoke::Script::Galaxy: scriptName = "galaxy"; break;
    case Smoke::Script::Observe: scriptName = "observe"; break;
    }
    std::fprintf(stderr, "PETARI SMOKE: script %s, frame limit %lu, stall limit %lu s\n", scriptName, frames, stall);
    std::fflush(stderr);
    Smoke::startWatchdog(static_cast<unsigned>(stall), 20);
}

// Game state is read here, before the seam releases the CPU, while this
// thread owns the game. Driver is Smoke::Driver or Smoke::StageDriver.
long gQuitDelayFrames = 0;  // PETARI_SMOKE_QUIT_DELAY frames left before the power button

template <class Driver>
void runSmoke(Driver* driver, bool probeHoldsA, bool probeOwnsInput, bool quitOnFinish = true) {
    Smoke::Observation observation = Smoke::observeGame(driver->wantsPlayer());
    observation.physical = Events::physicalInputs();
    const Smoke::Step step = driver->step(observation);
    for (const std::string& line : driver->log()) {
        std::fprintf(stderr, "PETARI SMOKE [frame %lu]: %s\n", driver->frame(), line.c_str());
    }
    if (!driver->log().empty()) {
        std::fflush(stderr);
    }
    if (step.assertFocus) {
        Events::assertFocus();
    }
    if (step.pointer) {
        // Normalised over the game image, as the input layer maps the pointer.
        Events::movePointer(gLastImage.x + step.pointerU * gLastImage.width,
                            gLastImage.y + step.pointerV * gLastImage.height);
    }
    for (const Smoke::Press& press : step.presses) {
        if ((probeOwnsInput && press.down) || (probeHoldsA && press.button == Smoke::Button::A)) {
            continue;  // PETARI_SKIP_PROBE holds Space (the script's A would release it); PETARI_POINT_PROBE drives
        }
        Events::pressButton(static_cast<int>(press.button), press.down);
    }
    if (step.menuWheel != 0.0f) {
        Events::menuWheel(step.menuWheel);
    }
    if (step.warp && !Smoke::warpPlayer(step)) {
        std::fprintf(stderr, "PETARI SMOKE: warp requested with no player to move\n");
    }
    Smoke::heartbeat(driver->frame(), driver->phase());
    if (step.requestQuit && !quitOnFinish) {
        for (Smoke::Button button : {Smoke::Button::A, Smoke::Button::B, Smoke::Button::StickUp,
             Smoke::Button::StickDown, Smoke::Button::StickLeft, Smoke::Button::StickRight,
             Smoke::Button::Spin, Smoke::Button::Plus, Smoke::Button::Minus}) {
            Events::pressButton(static_cast<int>(button), false);
        }
    }
    if (step.requestQuit && quitOnFinish) {
        // A route that passed while looking up layout panes/animations or sounds that do
        // not exist in the disc data did not really pass: those lookups were skipped.
        Smoke::Result result = driver->result();
        std::string reason = driver->reason();
        const uint64_t missingLayout = petari_layout_missing_reference_count();
        const uint64_t missingSound = petari_sound_missing_reference_count();
        const uint64_t manifestFailures = petari_gx_pipeline_manifest_failure_count();
        if ((missingLayout > 0 || missingSound > 0) &&
            (result == Smoke::Result::Pass || result == Smoke::Result::Assisted)) {
            result = Smoke::Result::Fail;
            reason += "; FAIL: missing asset references (layout " + std::to_string(missingLayout) + ", sound " +
                      std::to_string(missingSound) + "; see [layout]/[sound] missing lines)";
        }
        // A bundled stage shader manifest that exists but fails to load silently degrades
        // stage preparation to the shared fallback; treat it as a failed run.
        if (manifestFailures > 0 && (result == Smoke::Result::Pass || result == Smoke::Result::Assisted)) {
            result = Smoke::Result::Fail;
            reason += "; FAIL: " + std::to_string(manifestFailures) +
                      " pipeline manifest read failure(s) (see [gx stage prep] manifest read failed)";
        }
        Smoke::setProcessResult(result);
        // PETARI_SMOKE_QUIT_DELAY=<frames>: keep the game running that long after the result
        // (e.g. so PETARI_SKIP_PROBE sees what follows a story route's end), then power off.
        static const long quitDelay = [] {
            const char* value = std::getenv("PETARI_SMOKE_QUIT_DELAY");
            return value != nullptr ? std::atol(value) : 0L;
        }();
        std::fprintf(stderr, "PETARI SMOKE RESULT: %s (%s); pressing the power button%s%s\n",
                     Smoke::resultName(result), reason.c_str(),
                     observation.saveSequence ? " while the save-data sequence is active" : "",
                     quitDelay > 0 ? " after PETARI_SMOKE_QUIT_DELAY" : "");
        std::fflush(stderr);
        if (quitDelay > 0) {
            gQuitDelayFrames = quitDelay;
        } else {
            Smoke::noteQuitRequested(observation.saveSequence);
            Host::requestQuit();
        }
    }
    if (gQuitDelayFrames > 0 && --gQuitDelayFrames == 0) {
        Smoke::noteQuitRequested(observation.saveSequence);
        Host::requestQuit();
    }
}

double seconds(TraceClock::duration d) {
    return std::chrono::duration<double>(d).count();
}

void traceFrame(const Rect& image) {
    if (!gTrace.enabled) {
        return;
    }
    ++gTrace.frames;
    const bool first = gTrace.frames == 1;
    const auto now = TraceClock::now();
    if (!first) {
        const double frameMs = seconds(now - gTrace.previousFrame) * 1000.0;
        if (frameMs > gTrace.maxFrameMs) gTrace.maxFrameMs = frameMs;
        if (frameMs > 1000.0 / 30.0) ++gTrace.slowFrames;
    }
    gTrace.previousFrame = now;
    if (!first && gTrace.frames % kTraceInterval != 0) {
        return;
    }
    if (!first && gTiming.recorder != nullptr) {
        gTiming.recorder->writeWindow(stderr);
    }
    const double sinceLast = seconds(now - gTrace.last);
    std::fprintf(stderr,
                 "Petari trace: frame %lu%s at %.2f s (%.1f frames/s since last), image %.0fx%.0f at %.0f,%.0f, "
                 "unpresentable waits %lu, max interval %.2f ms, intervals over 33.3 ms %u\n",
                 gTrace.frames, first ? " (first frame reached the seam)" : "", seconds(now - gTrace.start),
                 first || sinceLast <= 0.0 ? 0.0 : (gTrace.frames - gTrace.lastFrames) / sinceLast, image.width, image.height, image.x, image.y,
                 gTrace.unpresentableWaits, gTrace.maxFrameMs, gTrace.slowFrames);
    std::fflush(stderr);
    gTrace.last = now;
    gTrace.lastFrames = gTrace.frames;
    gTrace.maxFrameMs = 0.0;
    gTrace.slowFrames = 0;
}

#ifdef PETARI_EDITOR_UI
// PETARI_EDITOR_MOUSE_TRACE=1: ImGui's mouse beside SDL's, when either changes (EP-001: panels ignore real
// clicks in a visible window). One line per change; quiet when nothing moves.
unsigned gImGuiMouseEvents = 0;  // SDL mouse events Aurora forwarded this run (counted in handleEvents)
void traceEditorMouse() {
    static const bool enabled = std::getenv("PETARI_EDITOR_MOUSE_TRACE") != nullptr;
    if (!enabled || ImGui::GetCurrentContext() == nullptr) return;
    const ImGuiIO& io = ImGui::GetIO();
    float sx = 0.0f, sy = 0.0f, gx = 0.0f, gy = 0.0f;
    const SDL_MouseButtonFlags sdlButtons = SDL_GetMouseState(&sx, &sy);
    SDL_GetGlobalMouseState(&gx, &gy);
    int wx = 0, wy = 0;
    if (gWindow != nullptr) SDL_GetWindowPosition(gWindow, &wx, &wy);
    SDL_Window* focus = SDL_GetKeyboardFocus();
    SDL_Window* mouseFocus = SDL_GetMouseFocus();
    const ImGuiWindow* hovered = GImGui->HoveredWindow;
    char line[512];
    std::snprintf(line, sizeof(line),
                  "imgui pos (%.0f,%.0f) down %d%d%d display %.0fx%.0f fb %.2f capture %d hovered '%s' active %u | sdl window (%.0f,%.0f) "
                  "buttons %u global (%.0f,%.0f) winpos (%d,%d) keyfocus %s mousefocus %s relative %d | events %u",
                  io.MousePos.x, io.MousePos.y, io.MouseDown[0], io.MouseDown[1], io.MouseDown[2], io.DisplaySize.x, io.DisplaySize.y,
                  io.DisplayFramebufferScale.x, io.WantCaptureMouse, hovered != nullptr ? hovered->Name : "-", GImGui->ActiveId,
                  sx, sy, static_cast<unsigned>(sdlButtons), gx, gy, wx, wy, focus == nullptr ? "none" : focus == gWindow ? "ours" : "other",
                  mouseFocus == nullptr ? "none" : mouseFocus == gWindow ? "ours" : "other",
                  gWindow != nullptr ? static_cast<int>(SDL_GetWindowRelativeMouseMode(gWindow)) : -1, gImGuiMouseEvents);
    static std::string last;
    // Compare without the event counter (it ticks with every motion).
    const std::string key(line, std::strstr(line, " | events") != nullptr ? std::strstr(line, " | events") - line : std::strlen(line));
    if (key == last) return;
    last = key;
    std::fprintf(stderr, "[editor-mouse] %s\n", line);
}
#endif

void handleEvents(const AuroraEvent* event) {
    for (; event != nullptr && event->type != AURORA_NONE; ++event) {
        switch (event->type) {
        case AURORA_EXIT:
            if (++gQuitRequests == 1) {
                std::fprintf(stderr, "Petari: quitting; close the window again to quit immediately\n");
                Host::requestQuit();
            } else {
                Host::forceQuit();
            }
            break;
        case AURORA_SDL_EVENT:
#ifdef PETARI_EDITOR_UI
            if (event->sdl.type >= SDL_EVENT_MOUSE_MOTION && event->sdl.type <= SDL_EVENT_MOUSE_WHEEL) ++gImGuiMouseEvents;
#endif
            if (event->sdl.type == SDL_EVENT_WINDOW_FOCUS_LOST) {
                gTiming.unfocused = gTiming.unfocusedInFrame = true;
            } else if (event->sdl.type == SDL_EVENT_WINDOW_FOCUS_GAINED) {
                gTiming.unfocused = false;
            } else if (event->sdl.type == SDL_EVENT_AUDIO_DEVICE_ADDED ||
                       event->sdl.type == SDL_EVENT_AUDIO_DEVICE_REMOVED ||
                       event->sdl.type == SDL_EVENT_AUDIO_DEVICE_FORMAT_CHANGED) {
                // Device switches migrate the stream and leave an audible gap; log them.
                std::fprintf(stderr, "[audio] SDL device event %s: device %u%s\n",
                             event->sdl.type == SDL_EVENT_AUDIO_DEVICE_ADDED     ? "added"
                             : event->sdl.type == SDL_EVENT_AUDIO_DEVICE_REMOVED ? "removed"
                                                                                  : "format changed",
                             static_cast<unsigned>(event->sdl.adevice.which),
                             event->sdl.adevice.recording ? " (recording)" : "");
            }
#ifdef PETARI_EDITOR_UI
            // A mod zip dropped on the window: the Install sheet (UX section 17).
            if (event->sdl.type == SDL_EVENT_DROP_FILE && event->sdl.drop.data != nullptr) {
                const std::string dropped = event->sdl.drop.data;
                if (dropped.size() > 4 && dropped.compare(dropped.size() - 4, 4, ".zip") == 0) PetariEditor::Ui::openInstallSheet(dropped.c_str());
                const auto extension = std::filesystem::path(dropped).extension().string();
                if (extension == ".gltf" || extension == ".glb" || extension == ".obj") PetariEditor::Ui::openImportSheet(dropped.c_str());  // M6 import
            }
#endif
            Display::handleEvent(event->sdl);
            if (!inputEvent(event->sdl.type) || gEarlyInputNs == 0 || event->sdl.common.timestamp > gEarlyInputNs) {
                Events::input(event->sdl);  // not already handed over before the game read its controllers
            }
            break;
        default:
            break;
        }
    }
    Display::update();
}

// Opens the next Aurora frame. While the window cannot present (minimized,
// hidden), aurora_update waits for window events and the game stays here.
// PETARI_TEST_FULLSCREEN="<seam>:<0|1>,...": enter (1) or leave (0) fullscreen at those seam
// counts, as Ctrl+Cmd+F would (SDL's desktop fullscreen: a macOS fullscreen Space). Test runs only.
void testFullscreen() {
    static const std::string plan = [] {
        const char* value = std::getenv("PETARI_TEST_FULLSCREEN");
        return std::string(value != nullptr ? value : "");
    }();
    if (plan.empty() || gWindow == nullptr) return;
    static unsigned long seams = 0;
    ++seams;
    std::size_t at = 0;
    while (at < plan.size()) {
        const std::size_t end = std::min(plan.find(',', at), plan.size());
        const std::string item = plan.substr(at, end - at);
        const std::size_t colon = item.find(':');
        if (colon != std::string::npos && colon + 1 < item.size() && std::strtoul(item.c_str(), nullptr, 10) == seams) {
            const bool on = item[colon + 1] == '1';
            const bool ok = SDL_SetWindowFullscreen(gWindow, on);
            std::fprintf(stderr, "PETARI TEST: %s fullscreen at seam %lu%s\n", on ? "entering" : "leaving", seams, ok ? "" : " (refused)");
        }
        at = end + 1;
    }
}

void openFrame() {
    while (!aurora_begin_frame()) {
        ++gTrace.unpresentableWaits;
        gTiming.unfocusedInFrame = true;
        handleEvents(aurora_update());
    }
}

// The game image in window points, told to the input layer when it changes.
Rect updateImage() {
    int windowWidth = 0;
    int windowHeight = 0;
    if (gWindow != nullptr) {
        SDL_GetWindowSize(gWindow, &windowWidth, &windowHeight);
    }
    Rect image;
    const bool known = gPresent.imageRect != nullptr && gPresent.imageRect(&image, gPresent.user);
    if (!known) {
        if (gPresent.imageRect == nullptr && !gWarnedImageRect) {
            gWarnedImageRect = true;
            std::fprintf(stderr,
                         "Petari: no presentation image rectangle; the pointer and overlays use the whole window\n");
        }
        image = {0.0f, 0.0f, static_cast<float>(windowWidth), static_cast<float>(windowHeight)};
    }
    const float width = static_cast<float>(windowWidth);
    const float height = static_cast<float>(windowHeight);
    if (image.x != gLastImage.x || image.y != gLastImage.y || image.width != gLastImage.width ||
        image.height != gLastImage.height || width != gLastWindowWidth || height != gLastWindowHeight) {
        gLastImage = image;
        gLastWindowWidth = width;
        gLastWindowHeight = height;
        Events::setImage(image, width, height);
    }
    return image;
}

}  // namespace

void setPresentHooks(const PresentHooks& hooks) {
    gPresent = hooks;
}

void setCpuRelease(const CpuRelease& release) {
    gRelease = release;
}

namespace Seam {

void attach(SDL_Window* window) {
    gWindow = window;
}

void openFirstFrame() {
    HostAllocationScope host;
    const char* trace = std::getenv("PETARI_TRACE_BOOT");
    gTrace.enabled = trace != nullptr && trace[0] != '\0' && trace[0] != '0';
    gTrace.start = gTrace.last = TraceClock::now();
    startTiming();
    startSmoke();
    if (gPresent.composeFrame == nullptr) {
        std::fprintf(stderr,
                     "Petari: no presentation hook; the window shows Aurora's frame as is (not the GXCopyDisp "
                     "image, and without VI black or dimming)\n");
    }
    if (gRelease.begin == nullptr || gRelease.end == nullptr) {
        std::fprintf(stderr,
                     "Petari: no CPU release for the frame seam; other game threads wait while the window "
                     "presents and handles events\n");
    }
    // As in the regular seam, other game threads run while the host opens the frame
    // (first-use Dawn/ImGui pipeline creation can take hundreds of milliseconds).
    const bool release = gRelease.begin != nullptr && gRelease.end != nullptr;
    if (release) {
        gRelease.begin();
    }
    handleEvents(aurora_update());
    openFrame();
    updateImage();
    if (release) {
        gRelease.end();
    }
    if (gTrace.enabled) {
        std::fprintf(stderr, "Petari trace: first Aurora frame open; starting the game\n");
        std::fflush(stderr);
    }
}

void setPhaseProbe(FrameStats::Phase (*probe)()) {
    gTiming.probe = probe;
}

const FrameStats::Recorder* frameStats() {
    return gTiming.recorder;
}

void reportFrameStats() {
    // Exit can come on a game thread whose plain new/delete use the game heap.
    HostAllocationScope host;
    SpikeProfiler::writeReport();
    static std::atomic<bool> reported{false};
    if (gTiming.recorder == nullptr || !gTiming.report || reported.exchange(true)) {
        return;
    }
    gTiming.recorder->writeSummary(stderr);
    PetariNative::PresentStats::writeSummary(stderr);
    PetariNative::PresentPacing::writeSummary(stderr);
    if (gExtraFrames + gLateSteps + gSlowDisplaySteps > 0) {
        std::fprintf(stderr, "Petari frame rate: %llu interpolated frames; without one: %llu steps presented late, %llu on a display below 100 Hz\n",
                     static_cast<unsigned long long>(gExtraFrames), static_cast<unsigned long long>(gLateSteps),
                     static_cast<unsigned long long>(gSlowDisplaySteps));
    }
    if (gTiming.csvPath != nullptr) {
        if (gTiming.recorder->writeCsv(gTiming.csvPath)) {
            std::fprintf(stderr, "Petari frame times: per-frame rows written to %s\n", gTiming.csvPath);
        } else {
            std::fprintf(stderr, "Petari frame times: cannot write %s\n", gTiming.csvPath);
        }
    }
    // Pipeline scheduler state at exit (pending/failed/skipped); normal exits skip aurora_shutdown.
    petari_gx_pipeline_report();
    std::fflush(stderr);
}

}  // namespace Seam

namespace AgentReplay {
    bool start(const std::string& route, const std::string& stage, int scenario, unsigned long frames, bool requireStar, std::string* error) {
        HostAllocationScope host;
        if (gAgentReplay && gAgentReplay->result() == Smoke::Result::Running) {
            *error = "a recorded route is already running";
            return false;
        }
        std::ifstream in(route);
        std::ostringstream text;
        text << in.rdbuf();
        Smoke::ReplayConfig config;
        config.stage = stage;
        config.scenario = scenario;
        config.routePath = route;
        config.route = Smoke::parseReplayRoute(text.str());
        config.requireStar = requireStar;
        config.startInStage = true;
        if (!in || config.route.size() < 2 || frames < 60 || frames > 1080000) {
            *error = "route needs a readable CSV with at least 2 waypoints and frame limit 60..1080000";
            return false;
        }
        delete gAgentReplay;
        gAgentMissingLayout = petari_layout_missing_reference_count();
        gAgentMissingSound = petari_sound_missing_reference_count();
        gAgentManifestFailures = petari_gx_pipeline_manifest_failure_count();
        gAgentAssetFailure = false;
        gAgentReplay = new Smoke::ReplayDriver(frames, config);
        return true;
    }
    bool active() {
        return gAgentReplay && gAgentReplay->result() == Smoke::Result::Running;
    }
    bool finished() {
        return gAgentReplay && gAgentReplay->result() != Smoke::Result::Running;
    }
    bool passed() {
        return gAgentReplay && gAgentReplay->result() == Smoke::Result::Pass && !gAgentAssetFailure;
    }
    std::string reason() {
        HostAllocationScope host;
        if (!gAgentReplay)
            return "no route";
        auto result = gAgentReplay->reason();
        if (gAgentReplay->result() == Smoke::Result::Pass && !passed())
            result += "; missing game assets or shader manifest failures (see server log)";
        return result;
    }
    unsigned long frame() {
        return gAgentReplay ? gAgentReplay->frame() : 0;
    }
    void cancel() {
        HostAllocationScope host;
        for (Smoke::Button button : {Smoke::Button::A, Smoke::Button::B, Smoke::Button::StickUp, Smoke::Button::StickDown, Smoke::Button::StickLeft,
                                     Smoke::Button::StickRight, Smoke::Button::Spin, Smoke::Button::Plus, Smoke::Button::Minus})
            Events::pressButton(static_cast< int >(button), false);
        delete gAgentReplay;
        gAgentReplay = nullptr;
    }
}  // namespace AgentReplay

}  // namespace PetariNative::App

using namespace PetariNative::App;

namespace {
// Input that came since the seam pumped events, handed to the game before it reads its
// controllers (native/INPUT_LATENCY.md): keys, the mouse and controllers only, in the order they
// came. They stay queued for the seam's aurora_update (ImGui and window handling see them
// there), which then skips them for the game. Input::sampleNow puts them into a Wii Remote
// report at once instead of up to 5 ms later. Without this a key pressed just after the seam
// waited for the next frame's seam.
void takeInputEarly() {
    PetariNative::HostAllocationScope host;  // SDL and AppKit allocate while pumping
    SDL_PumpEvents();
    SDL_Event events[96];
    int count = std::max(SDL_PeepEvents(events, 64, SDL_PEEKEVENT, SDL_EVENT_KEY_DOWN, SDL_EVENT_MOUSE_WHEEL), 0);
    count += std::max(SDL_PeepEvents(events + count, 32, SDL_PEEKEVENT, SDL_EVENT_GAMEPAD_AXIS_MOTION, SDL_EVENT_GAMEPAD_BUTTON_UP), 0);
    std::sort(events, events + count, [](const SDL_Event& a, const SDL_Event& b) { return a.common.timestamp < b.common.timestamp; });
    for (int i = 0; i < count; i++) {
        if (events[i].common.timestamp > gEarlyInputNs) {
            Events::input(events[i]);
            gEarlyInputNs = events[i].common.timestamp;
        }
    }
    PetariNative::Input::sampleNow();
}
}  // namespace

// PETARI_INPUT_LATENCY=reduced: the loop computes each step first and draws it at once.
extern "C" int petari_host_input_first(void) {
    // PETARI_INPUT_LATENCY=reduced|original overrides the Graphics page for a run.
    static const int forced = [] {
        const char* value = std::getenv("PETARI_INPUT_LATENCY");
        if (value == nullptr) return -1;
        return std::strcmp(value, "reduced") == 0 ? 1 : std::strcmp(value, "original") == 0 ? 0 : -1;
    }();
    gInputFirst = forced >= 0 ? forced == 1
                              : PetariNative::Graphics::current().inputLatency == PetariNative::Graphics::InputLatency::Reduced;
    gExtraThisStep = false;
    return gInputFirst ? 1 : 0;
}

extern "C" void petari_host_frame_mark(int mark) {
    const std::uint64_t now = Telemetry::nowNs();
    if (mark == PETARI_FRAME_MARK_RETRACE_DONE) {
        gTiming.retraceDone = now;
        // The retrace that ended the wait, if one came after the seam.
        const std::uint64_t retrace = Telemetry::lastRetraceNs.load(std::memory_order_relaxed);
        gTiming.retraceWake = retrace > gTiming.lastExit && retrace <= now ? now - retrace : 0;
        takeInputEarly();
    } else if (mark == PETARI_FRAME_MARK_END_FRAME) {
        gTiming.endFrame = now;
    } else if (mark == PETARI_FRAME_MARK_UPDATED) {
        PetariNative::LatencyProbe::noteUpdated();
    }
}

extern "C" void petari_host_frame_seam(void) {
    const std::uint64_t entry = Telemetry::nowNs();
    PetariNative::HostAllocationScope host;
    publishFrameRateStatus(entry);
    recordRouteFrame(SmokeBackground::enabled);
    observeProgressFrame();
    // Game state is readable here, before the CPU is released.
    recordFrame(entry, gTiming.probe != nullptr ? gTiming.probe() : FrameStats::Phase::Gameplay);
    const bool probeHoldsA = Smoke::skipProbeFrame();
    if (float u = 0.0f, v = 0.0f; Smoke::skipProbeAnswerPointer(&u, &v)) {
        Events::movePointer(gLastImage.x + u * gLastImage.width, gLastImage.y + v * gLastImage.height);
    }
    const Smoke::PointProbeStep point = Smoke::pointProbeFrame();
    if (point.pointer) {
        Events::movePointer(gLastImage.x + point.u * gLastImage.width, gLastImage.y + point.v * gLastImage.height);
    }
    if (gAgentReplay != nullptr && !AgentReplay::finished()) {
        runSmoke(gAgentReplay, false, false, false);
        if (AgentReplay::finished()) {
            gAgentAssetFailure = petari_layout_missing_reference_count() != gAgentMissingLayout ||
                                 petari_sound_missing_reference_count() != gAgentMissingSound ||
                                 petari_gx_pipeline_manifest_failure_count() != gAgentManifestFailures;
        }
    } else if (gSmoke != nullptr) {
        runSmoke(gSmoke, probeHoldsA, point.active);
    } else if (gStage != nullptr) {
        runSmoke(gStage, probeHoldsA, point.active);
    } else if (gSoak != nullptr) {
        runSmoke(gSoak, probeHoldsA, point.active);
    } else if (gGoodEgg != nullptr) {
        runSmoke(gGoodEgg, probeHoldsA, point.active);
    } else if (gDomes != nullptr) {
        runSmoke(gDomes, probeHoldsA, point.active);
    } else if (gReplay != nullptr) {
        runSmoke(gReplay, probeHoldsA, point.active);
    } else if (gMovement != nullptr) {
        runSmoke(gMovement, probeHoldsA, point.active);
    }
    if (Soak::telemetryActive()) {  // PETARI_SOAK_CSV: frame times and, periodically, the JKR heaps
        static unsigned long frames = 0;
        Soak::gameFrame(++frames, gSoak != nullptr ? gSoak->cycle() : 0, gSoak != nullptr ? gSoak->phase() : "");
    }
    const bool release = gRelease.begin != nullptr && gRelease.end != nullptr;
    if (release) {
        gRelease.begin();
    }

    const std::uint64_t composeStart = Telemetry::nowNs();
    if (gPresent.composeFrame != nullptr) {
        gPresent.composeFrame(gPresent.user);
    }
    const Rect image = updateImage();
    traceFrame(image);
#ifdef PETARI_EDITOR_UI
    // The level editor's panels, around the game (they set where the next frame's image goes).
    PetariEditor::Ui::drawFrame(gLastWindowWidth, gLastWindowHeight);
#endif
#ifdef PETARI_EDITOR_UI
    traceEditorMouse();
#endif
    PetariNative::HomeMenu::drawImGuiOverlay(image.x, image.y, image.width, image.height);
    StatsOverlay::draw(gWindow, image.x, image.y, image.width, image.height);
    if (gInputFirst && gExtraThisStep) {
        // Input latency Reduced: the step's frame comes half an interval after its extra frame.
        const std::uint64_t due = gExtraPresentNs + kRetraceNs / 2;
        const std::uint64_t now = Telemetry::nowNs();
        if (now < due) {
            SDL_DelayPrecise(due - now);
        }
    }
    const std::uint64_t endStart = Telemetry::nowNs();
    gStepPresentNs = endStart;
    aurora_end_frame();
    StatsOverlay::notePresent();

    const std::uint64_t beginStart = Telemetry::nowNs();
    testFullscreen();  // PETARI_TEST_FULLSCREEN
    handleEvents(aurora_update());
    openFrame();

    const std::uint64_t reacquireStart = Telemetry::nowNs();
    if (release) {
        gRelease.end();
    }
    const std::uint64_t exit = Telemetry::nowNs();
    gTiming.seamNs[0] = endStart - composeStart;
    gTiming.seamNs[1] = beginStart - endStart;
    gTiming.seamNs[2] = reacquireStart - beginStart;
    gTiming.seamNs[3] = exit - reacquireStart;
    gTiming.lastExit = exit;
}

// Frame interpolation (native/FRAME_RATE.md): the extra frame is drawn right after the step's
// present and shown half a retrace interval after it, so that presents come evenly; the next
// step's present comes the same draw time after the next retrace. A step presented in the
// second half of its interval is late: then there is no extra frame.
extern "C" int petari_host_interp_wait(void) {
    if (PetariNative::Graphics::current().frameRate < 120) {
        return 0;
    }
    ++gInterpolationSecond.asked;
    // A display below 100 Hz cannot show the extra frames; an unknown rate is allowed. A background
    // smoke run's window is never seen, so its display does not matter.
    if (!SmokeBackground::enabled && gDisplayHz > 0 && gDisplayHz < 100) {
        ++gSlowDisplaySteps;
        return 0;
    }
    const std::uint64_t retrace = Telemetry::lastRetraceNs.load(std::memory_order_relaxed);
    const std::uint64_t now = Telemetry::nowNs();
    // The extra frame is shown half a retrace interval away from the step's frame, so that presents
    // come evenly. In the Wii's order it follows the step's present, which must have come in the
    // first half of its interval. With Input latency Reduced it comes first: it must be drawn within
    // the first half, so that the step's frame, half an interval later, keeps its time.
    const bool late = gInputFirst ? retrace == 0 || now + gExtraFrameNs > retrace + kRetraceNs / 2
                                  : retrace == 0 || gStepPresentNs < retrace || gStepPresentNs > retrace + kRetraceNs / 2;
    if (late) {
        ++gLateSteps;
        ++gInterpolationSecond.late;
        gExtraFrameNs -= gExtraFrameNs / 16;  // an estimate that only grows would never allow one again
        return 0;
    }
    gExtraStartNs = now;
    return 1;
}

// The extra frame's present: as the seam, without route recording, progress, frame statistics
// or smoke drivers, which run once per game step.
extern "C" void petari_host_present_seam(void) {
    PetariNative::HostAllocationScope host;
    const bool release = gRelease.begin != nullptr && gRelease.end != nullptr;
    if (release) {
        gRelease.begin();
    }
    if (gPresent.composeFrame != nullptr) {
        gPresent.composeFrame(gPresent.user);
    }
    const Rect image = updateImage();
    PetariNative::HomeMenu::drawImGuiOverlay(image.x, image.y, image.width, image.height);
    StatsOverlay::draw(gWindow, image.x, image.y, image.width, image.height);
    const std::uint64_t drawn = Telemetry::nowNs();
    if (drawn > gExtraStartNs) {
        gExtraFrameNs = (gExtraFrameNs * 3 + std::min<std::uint64_t>(drawn - gExtraStartNs, 12000000)) / 4;
    }
    if (!gInputFirst) {
        const std::uint64_t due = gStepPresentNs + kRetraceNs / 2;
        if (drawn < due) {
            SDL_DelayPrecise(due - drawn);
        }
    }
    aurora_end_frame();
    gExtraPresentNs = Telemetry::nowNs();
    gExtraThisStep = true;
    StatsOverlay::notePresent();
    ++gExtraFrames;
    ++gInterpolationSecond.drawn;
    handleEvents(aurora_update());
    openFrame();
    if (release) {
        gRelease.end();
    }
}

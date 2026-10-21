// The per-frame host seam (petari/app.hpp). Aurora and SDL side.

#include <aurora/aurora.h>
#include <aurora/event.h>
#include <aurora/gfx.h>

#include <SDL3/SDL_timer.h>
#include <SDL3/SDL_video.h>
#include <mach/mach_time.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
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
#include "smoke_goodegg.hpp"
#include "smoke_soak.hpp"
#include "smoke_stage.hpp"
#include "soak_telemetry.hpp"
#include "stats_overlay.hpp"
#include "display_link.hpp"
#include "petari/asset_diagnostics.hpp"
#include "petari/display_mode.hpp"
#include "petari/display_sync.hpp"
#include "petari/frame_telemetry.hpp"
#include "petari/graphics.hpp"
#include "petari/home_menu.hpp"
#include "petari/host_allocation.hpp"
#include "petari/test_fixture.hpp"

namespace PetariNative::App {

namespace {

PresentHooks gPresent;
CpuRelease gRelease;
constexpr std::uint64_t kRetraceNs = 16683333;  // 59.94 Hz
std::uint64_t gStepPresentNs = 0;  // the step's aurora_end_frame, for frame interpolation's extra frame
std::uint64_t gStepReadyNs = 0;    // when the step's frame was ready to present (before a V-Sync wait)
std::uint64_t gExtraFrames = 0;    // frame interpolation's presents, in the frame time report
std::uint64_t gLateSteps = 0;      // steps without an extra frame: presented too late
std::uint64_t gSlowDisplaySteps = 0;  // or on a display below 100 Hz
int gDisplayHz = 0;                // the window's display, checked once a second; 0: unknown
// V-Sync (Graphics::VSync, petari/display_sync.hpp, native/FRAME_RATE.md). The mode and whether
// Variable is in effect are decided once a second (publishFrameRateStatus).
PetariNative::Graphics::VSync gVsyncMode = PetariNative::Graphics::VSync::On;
bool gVariableActive = false;  // Variable on a variable-refresh display in fullscreen: it follows the game's clock
bool gPresentSynced = false;   // the retraces follow the display's refreshes (On, Low latency)
bool gPresentFifo = false;     // frames are presented in FIFO order on refreshes (synced or Variable)
// The extra frame's draw, averaged, for the V-Sync gate. A sample counts at most 12 ms, and every
// step left without an extra frame takes a sixteenth off: one long draw (a shader compile) once
// made it so large that no extra frame was drawn again, and so none could bring it down.
std::uint64_t gExtraFrameNs = 4000000;
std::uint64_t gExtraStartNs = 0;
std::uint64_t gStepRetraceNs = 0;  // the retrace that started this game step
std::uint64_t gStepGridNs = 0;     // synced: the refresh that retrace belongs to (Low latency raises it later)
std::uint64_t gVariableDelayNs = 8000000;  // Variable: the step's frame is presented this long after its retrace
unsigned gCleanSteps = 0;          // steps since a frame missed its time (Low latency, Variable)

double nsPerTick() {
    static const double ns = [] {
        mach_timebase_info_data_t timebase;
        mach_timebase_info(&timebase);
        return static_cast<double>(timebase.numer) / timebase.denom;
    }();
    return ns;
}

// When a step's frames are presented. slot 0 is the step's frame, slot 1 the extra frame.
// - Synced (On, Low latency): each frame has its refresh, a fixed number of refreshes after the
//   refresh of the step's retrace whatever its draw time: the step's frame one retrace later (on a
//   120 Hz display the second refresh), the extra frame half a retrace after that. A frame is
//   presented between 1 ms after the refresh before its own (so that it is not shown on that one)
//   and 3 ms before its own (so that it is drawn and taken in time). Presenting it at the end of
//   that window instead leaves the extra frame less time: measured, it lost more of them.
// - Variable: the display shows a frame when it comes, so the frames are presented at fixed
//   times after the step's retrace: gVariableDelayNs, and half a retrace later.
// presentDue is the start of the window (0: at once), presentEnd its end; both 0 for V-Sync Off.
std::uint64_t presentWindow(int slot, bool end) {
    namespace Sync = PetariNative::DisplaySync;
    if (gVariableActive) {
        if (gStepRetraceNs == 0) {
            return 0;
        }
        const std::uint64_t due = gStepRetraceNs + gVariableDelayNs + static_cast<std::uint64_t>(slot) * (kRetraceNs / 2);
        return end ? due + 1000000 : due;
    }
    const int every = Sync::every.load(std::memory_order_relaxed);
    if (!gPresentSynced || every < 1 || gStepGridNs == 0) {
        return 0;
    }
    const std::uint64_t period = static_cast<std::uint64_t>(Sync::periodTicks.load(std::memory_order_relaxed) * nsPerTick());
    const std::uint64_t refreshes = static_cast<std::uint64_t>(every - 1 + slot * (every / 2));
    if (end) {
        return gStepGridNs + (refreshes + 1) * period - 3000000;
    }
    return refreshes == 0 ? 0 : gStepGridNs + refreshes * period + 1000000;
}

std::uint64_t presentDue(int slot) {
    return presentWindow(slot, false);
}

std::uint64_t presentEnd(int slot) {
    return presentWindow(slot, true);
}

// Low latency and Variable find the shortest wait the draw times allow: each frame that misses its
// time takes some back at once, and every second (60 steps) without a miss gives a little.
// Low latency raises the retraces later after their refresh (DisplaySync::phaseTicks), up to
// 7 ms before the step's frame is due; Variable presents the step's frame sooner after its retrace.
void adjustPacing(bool missed) {
    namespace Sync = PetariNative::DisplaySync;
    if (gPresentSynced && gVsyncMode == PetariNative::Graphics::VSync::LowLatency) {
        const double period = static_cast<double>(Sync::periodTicks.load(std::memory_order_relaxed)) * nsPerTick();
        const double longest = std::max(0.0, Sync::every.load(std::memory_order_relaxed) * period - 7000000.0);
        double phase = static_cast<double>(Sync::phaseTicks.load(std::memory_order_relaxed)) * nsPerTick();
        if (missed) {
            phase = std::max(0.0, phase - 1000000.0);
            gCleanSteps = 0;
        } else if (++gCleanSteps >= 60) {
            gCleanSteps = 0;
            phase = std::min(longest, phase + 250000.0);
        }
        Sync::phaseTicks.store(static_cast<std::uint64_t>(phase / nsPerTick()), std::memory_order_relaxed);
    } else if (gVariableActive) {
        if (missed) {
            gVariableDelayNs = std::min<std::uint64_t>(gVariableDelayNs + 500000, 14000000);
            gCleanSteps = 0;
        } else if (++gCleanSteps >= 60) {
            gCleanSteps = 0;
            gVariableDelayNs = std::max<std::uint64_t>(gVariableDelayNs - 100000, 3000000);
        }
    }
}

void waitUntil(std::uint64_t due) {
    const std::uint64_t now = PetariNative::FrameTelemetry::nowNs();
    if (due != 0 && now < due) {
        SDL_DelayPrecise(due - now);
    }
}

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
    namespace Graphics = PetariNative::Graphics;
    gVsyncMode = Graphics::current().vsync;
    // PETARI_VARIABLE_REFRESH=1: Variable as on a variable-refresh display in fullscreen, for
    // measuring its pacing in a background smoke run.
    static const bool forceVariable = [] {
        const char* value = std::getenv("PETARI_VARIABLE_REFRESH");
        return value != nullptr && value[0] == '1';
    }();
    gVariableActive = gVsyncMode == Graphics::VSync::Variable &&
                      (forceVariable || (Display::fullscreen() && DisplayLink::variableRefresh(gWindow)));
    DisplayLink::follow(gWindow, gVsyncMode == Graphics::VSync::On || gVsyncMode == Graphics::VSync::LowLatency ||
                                     (gVsyncMode == Graphics::VSync::Variable && !gVariableActive));
    if (gVsyncMode != Graphics::VSync::LowLatency) {
        PetariNative::DisplaySync::phaseTicks.store(0, std::memory_order_relaxed);
    }
    PetariNative::Graphics::FrameRateStatus status;
    status.displayHz = gDisplayHz;
    status.variableRefresh = gVariableActive;
    if (second.asked > 0) {
        status.interpolatedPercent = static_cast<int>(second.drawn * 100 / second.asked);
        status.latePercent = static_cast<int>(second.late * 100 / second.asked);
    }
    PetariNative::Graphics::setFrameRateStatus(status);
    second = InterpolationSecond{};
    second.start = now;
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
template <class Driver>
void runSmoke(Driver* driver) {
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
        Events::pressButton(static_cast<int>(press.button), press.down);
    }
    if (step.warp && !Smoke::warpPlayer(step)) {
        std::fprintf(stderr, "PETARI SMOKE: warp requested with no player to move\n");
    }
    Smoke::heartbeat(driver->frame(), driver->phase());
    if (step.requestQuit) {
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
        Smoke::noteQuitRequested(observation.saveSequence);
        std::fprintf(stderr, "PETARI SMOKE RESULT: %s (%s); pressing the power button%s\n",
                     Smoke::resultName(result), reason.c_str(),
                     observation.saveSequence ? " while the save-data sequence is active" : "");
        std::fflush(stderr);
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
            Display::handleEvent(event->sdl);
            Events::input(event->sdl);
            break;
        default:
            break;
        }
    }
    Display::update();
}

// Opens the next Aurora frame. While the window cannot present (minimized,
// hidden), aurora_update waits for window events and the game stays here.
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
    DisplayLink::writeReport();
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

}  // namespace PetariNative::App

using namespace PetariNative::App;

extern "C" void petari_host_frame_mark(int mark) {
    const std::uint64_t now = Telemetry::nowNs();
    if (mark == PETARI_FRAME_MARK_RETRACE_DONE) {
        gTiming.retraceDone = now;
        // The retrace that ended the wait, if one came after the seam.
        const std::uint64_t retrace = Telemetry::lastRetraceNs.load(std::memory_order_relaxed);
        gStepRetraceNs = retrace;
        const double phase = static_cast<double>(PetariNative::DisplaySync::retracePhaseTicks.load(std::memory_order_relaxed)) * nsPerTick();
        gStepGridNs = retrace > phase ? retrace - static_cast<std::uint64_t>(phase) : retrace;
        gTiming.retraceWake = retrace > gTiming.lastExit && retrace <= now ? now - retrace : 0;
    } else if (mark == PETARI_FRAME_MARK_END_FRAME) {
        gTiming.endFrame = now;
    }
}

extern "C" void petari_host_frame_seam(void) {
    const std::uint64_t entry = Telemetry::nowNs();
    PetariNative::HostAllocationScope host;
    publishFrameRateStatus(entry);
    // FIFO presents only while the retraces follow the display, or the display follows the game
    // (Variable): on the timer's own 59.94 Hz they would drift against fixed refreshes.
    gPresentSynced = PetariNative::DisplaySync::synced.load(std::memory_order_relaxed);
    if (const bool fifo = gPresentSynced || gVariableActive; fifo != gPresentFifo) {
        gPresentFifo = fifo;
        aurora_enable_vsync(fifo);
    }
    recordRouteFrame(SmokeBackground::enabled);
    observeProgressFrame();
    // Game state is readable here, before the CPU is released.
    recordFrame(entry, gTiming.probe != nullptr ? gTiming.probe() : FrameStats::Phase::Gameplay);
    if (gSmoke != nullptr) {
        runSmoke(gSmoke);
    } else if (gStage != nullptr) {
        runSmoke(gStage);
    } else if (gSoak != nullptr) {
        runSmoke(gSoak);
    } else if (gGoodEgg != nullptr) {
        runSmoke(gGoodEgg);
    } else if (gDomes != nullptr) {
        runSmoke(gDomes);
    } else if (gReplay != nullptr) {
        runSmoke(gReplay);
    } else if (gMovement != nullptr) {
        runSmoke(gMovement);
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
    PetariNative::HomeMenu::drawImGuiOverlay(image.x, image.y, image.width, image.height);
    StatsOverlay::draw(gWindow, image.x, image.y, image.width, image.height);
    const std::uint64_t ready = Telemetry::nowNs();
    gStepReadyNs = ready;
    waitUntil(presentDue(0));
    adjustPacing(gVariableActive ? ready > presentEnd(0) : ready > presentEnd(0) && presentEnd(0) != 0);
    const std::uint64_t endStart = Telemetry::nowNs();
    gStepPresentNs = endStart;
    aurora_end_frame();
    StatsOverlay::notePresent();
    DisplayLink::notePresent();

    const std::uint64_t beginStart = Telemetry::nowNs();
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
// present. With V-Sync it is presented in its window (presentDue(1) to presentEnd(1))
// and shown on the refresh after the step's frame. Without, it is shown half a
// retrace interval after the step's, so that presents come evenly, and a step presented in the
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
    // With V-Sync the extra frame goes on the refresh after the step's by itself; it only has to
    // be drawn before the next retrace. Without, it is shown half a retrace after the step's.
    // With V-Sync the extra frame must be drawn before its window closes (presentEnd(1)). After a
    // step's frame that missed its own window (it is shown a refresh late) there is none: it would
    // wait behind that frame and push every later frame a refresh back.
    const bool late = gVariableActive  ? gStepRetraceNs == 0 || now + gExtraFrameNs + 500000 > presentEnd(1)
                      : gPresentSynced ? gStepGridNs == 0 || gStepReadyNs > presentEnd(0) ||
                                             now + gExtraFrameNs + 500000 > presentEnd(1)
                                     : retrace == 0 || gStepPresentNs < retrace || gStepPresentNs > retrace + kRetraceNs / 2;
    if (late) {
        ++gLateSteps;
        ++gInterpolationSecond.late;
        gExtraFrameNs -= gExtraFrameNs / 16;
        if (gPresentSynced && gStepReadyNs <= presentEnd(0)) {
            adjustPacing(true);  // no time left for the extra frame: Low latency waits less close
        }
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
    const std::uint64_t now = Telemetry::nowNs();
    if (now > gExtraStartNs) {
        gExtraFrameNs = (gExtraFrameNs * 3 + std::min<std::uint64_t>(now - gExtraStartNs, 12000000)) / 4;
    }
    waitUntil(gPresentFifo ? presentDue(1) : gStepPresentNs + kRetraceNs / 2);
    aurora_end_frame();
    StatsOverlay::notePresent();
    DisplayLink::notePresent();
    ++gExtraFrames;
    ++gInterpolationSecond.drawn;
    handleEvents(aurora_update());
    openFrame();
    if (release) {
        gRelease.end();
    }
}

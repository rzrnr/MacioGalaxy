// Tests for native VI: retrace interrupts, callback order, VIFlush latching,
// renderer hooks, VIWaitForRetrace on OS threads, dimming, and the realtime
// retrace clock.

#include <revolution/os.h>
#include <revolution/vi.h>

#include <sys/wait.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <functional>
#include <string>
#include <thread>
#include <vector>

#include "petari/display_sync.hpp"
#include "petari/platform/sc.hpp"
#include "petari/platform/vi.hpp"

extern "C" void __OSThreadInit(void);

namespace PVI = PetariNative::Platform::VI;
namespace PSC = PetariNative::Platform::SC;

namespace {

int checks = 0;
void check(bool condition, const char* label) {
    ++checks;
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", label);
        std::exit(1);
    }
}

bool aborts(const std::function<void()>& fn) {
    std::fflush(nullptr);
    const pid_t pid = ::fork();
    if (pid == 0) {
        std::freopen("/dev/null", "w", stderr);
        fn();
        ::_exit(0);
    }
    int status = 0;
    ::waitpid(pid, &status, 0);
    return WIFSIGNALED(status) && WTERMSIG(status) == SIGABRT;
}

// Deterministic clock: each retrace is raised on a separate host thread (the
// interrupt context) and joined.
void retrace(int count = 1) {
    for (int i = 0; i < count; ++i) {
        std::thread source([] { PVI::signalRetrace(); });
        source.join();
    }
}

GXRenderModeObj renderMode(VITVMode mode, u16 width, u16 height) {
    GXRenderModeObj rm{};
    rm.viTVmode = mode;
    rm.fbWidth = width;
    rm.efbHeight = height;
    rm.xfbHeight = height;
    rm.viWidth = width;
    rm.viHeight = height;
    return rm;
}

std::vector<std::string> gEvents;
std::atomic<int> gLatchedCalls{0};
PVI::DisplayState gLastLatched;
const GXRenderModeObj* gConfigured;

void preRetrace(u32 count) {
    check(OSDisableInterrupts() == FALSE, "pre-retrace callback runs with interrupts disabled");
    gEvents.push_back("pre" + std::to_string(count));
}

void postRetrace(u32 count) {
    check(OSDisableInterrupts() == FALSE, "post-retrace callback runs with interrupts disabled");
    gEvents.push_back("post" + std::to_string(count));
}

void onLatched(const PVI::DisplayState& state, void*) {
    check(OSDisableInterrupts() == FALSE, "latch hook runs in interrupt context");
    gEvents.push_back("latch" + std::to_string(state.retraceCount));
    gLastLatched = state;
    gLatchedCalls++;
}

void onConfigure(const GXRenderModeObj* rm, void* user) {
    gConfigured = rm;
    *static_cast<int*>(user) += 1;
}

void testExternalClockLatching() {
    PVI::setClock(PVI::Clock::External);
    VIInit();
    VIInit();  // idempotent
    PVI::DisplayState s = PVI::displayState();
    check(s.black && s.frameBuffer == nullptr && !s.configured && s.retraceCount == 0, "VI starts black with no framebuffer");
    check(VIGetTvFormat() == VI_NTSC && s.fieldRate > 59.93 && s.fieldRate < 59.95, "boot mode NTSC at 59.94 Hz");

    int configureCalls = 0;
    PVI::setHooks({onConfigure, onLatched, &configureCalls});
    check(VISetPreRetraceCallback(preRetrace) == nullptr && VISetPostRetraceCallback(postRetrace) == nullptr, "install callbacks");

    retrace();
    check(VIGetRetraceCount() == 1 && (gEvents == std::vector<std::string>{"pre1", "post1"}), "retrace without flush: no latch");

    static u8 xfb1[64], xfb2[64];
    VISetNextFrameBuffer(xfb1);
    VISetBlack(FALSE);
    retrace();
    check(PVI::displayState().black && VIGetCurrentFrameBuffer() == nullptr, "unflushed changes are not shown");

    VIFlush();
    check(VIGetNextFrameBuffer() == xfb1 && VIGetCurrentFrameBuffer() == nullptr, "VIFlush arms the next framebuffer");
    gEvents.clear();
    retrace();
    check((gEvents == std::vector<std::string>{"pre3", "latch3", "post3"}), "latch happens between pre and post callbacks");
    s = PVI::displayState();
    check(s.frameBuffer == xfb1 && !s.black && VIGetCurrentFrameBuffer() == xfb1, "retrace latches framebuffer and unblanks");
    check(gLastLatched.frameBuffer == xfb1 && gLatchedCalls == 1, "renderer hook receives latched state");

    retrace();
    check(gLatchedCalls == 1, "flushed state latches once");

    // Render mode: hook immediately, latched at the next flushed retrace.
    const GXRenderModeObj pal = renderMode(VI_TVMODE_PAL_INT, 640, 528);
    VIConfigure(&pal);
    check(configureCalls == 1 && gConfigured == &pal, "VIConfigure calls the configure hook on the game thread");
    check(VIGetTvFormat() == VI_NTSC, "configuration waits for flush and retrace");
    VISetNextFrameBuffer(xfb2);
    VISetBlack(TRUE);
    VIConfigurePan(8, 4, 624, 520);
    VISetTrapFilter(VI_TRUE);
    VIFlush();
    retrace();
    s = PVI::displayState();
    check(s.configured && s.tvFormat == VI_PAL && s.fieldRate == 50.0 && s.renderMode.efbHeight == 528, "PAL mode latched at 50 Hz");
    check(s.frameBuffer == xfb2 && s.black && s.panX == 8 && s.panWidth == 624 && s.trapFilter, "all flushed state latches together");
    check(VIGetScanMode() == VI_INTERLACE, "interlaced scan mode");

    const GXRenderModeObj prog = renderMode(VI_TVMODE_NTSC_PROG, 640, 480);
    VIConfigure(&prog);
    VIFlush();
    retrace();
    check(VIGetScanMode() == VI_PROGRESSIVE && VIGetTvFormat() == VI_NTSC && PVI::displayState().panHeight == 480,
          "progressive NTSC; VIConfigure resets panning");
    check(PVI::fieldRateFor(VI_TVMODE_EURGB60_INT) > 59.9 && PVI::fieldRateFor(VI_TVMODE_PAL_INT) == 50.0, "field rates");
    check(VIGetDTVStatus() == 1, "digital display reported");

    check(VISetPreRetraceCallback(nullptr) == preRetrace && VISetPostRetraceCallback(nullptr) == postRetrace, "callbacks replaced");
    PVI::setHooks({});
}

// ---- VIWaitForRetrace on OS threads ----

std::atomic<bool> gStopClock{false};
std::atomic<int> gSpins{0};

void* spinner(void*) {
    while (!gStopClock) {
        gSpins++;
        OSYieldThread();
    }
    return nullptr;
}

OSMessageQueue gRetraceMessages;
OSMessage gRetraceSlots[8];
void postToQueue(u32 count) {
    // JUTVideo pattern: a retrace callback posts to a game message queue.
    OSSendMessage(&gRetraceMessages, reinterpret_cast<OSMessage>(static_cast<uintptr_t>(count)), OS_MESSAGE_NOBLOCK);
}

void testWaitForRetraceOnOsThreads() {
    gStopClock = false;
    std::thread clock([] {
        while (!gStopClock) {
            std::this_thread::sleep_for(std::chrono::milliseconds(2));
            PVI::signalRetrace();
        }
    });

    // A lower-priority thread runs while the main thread sleeps on the retrace queue.
    static OSThread thread;
    alignas(32) static u8 stack[0x4000];
    OSCreateThread(&thread, spinner, nullptr, stack + sizeof(stack), sizeof(stack), 24, 0);
    OSResumeThread(&thread);

    u32 last = VIGetRetraceCount();
    for (int i = 0; i < 20; ++i) {
        VIWaitForRetrace();
        const u32 now = VIGetRetraceCount();
        check(now > last, "VIWaitForRetrace returns after a new retrace");
        last = now;
    }
    for (int i = 0; i < 200 && gSpins.load() == 0; ++i) {
        VIWaitForRetrace();
    }
    check(gSpins.load() > 0, "lower-priority OS thread runs while main waits for retrace");

    OSInitMessageQueue(&gRetraceMessages, gRetraceSlots, 8);
    VISetPostRetraceCallback(postToQueue);
    OSMessage msg;
    OSReceiveMessage(&gRetraceMessages, &msg, OS_MESSAGE_BLOCK);
    check(reinterpret_cast<uintptr_t>(msg) > 0, "retrace callback message wakes an OS thread");
    VISetPostRetraceCallback(nullptr);

    gStopClock = true;
    clock.join();
    OSJoinThread(&thread, nullptr);
}

void testDimming() {
    PSC::reset();  // screen saver on by default
    check(VIEnableDimming(TRUE) == TRUE, "dimming enabled by default");
    VIResetDimmingCount();  // earlier tests' retraces counted as idle
    retrace();
    check(VIGetDimmingCount() == 18000, "five minutes of NTSC retraces until dimming");
    std::thread source([] {
        for (int i = 0; i < 18000; ++i) {
            PVI::signalRetrace();
        }
    });
    source.join();
    check(PVI::displayState().dimmed && VIGetDimmingCount() == 0, "idle display dims");
    VIResetDimmingCount();
    retrace();
    check(!PVI::displayState().dimmed && VIGetDimmingCount() == 18000, "activity undims at the next retrace");
    check(VIEnableDimming(FALSE) == TRUE, "disable dimming");
    retrace(3);
    check(VIGetDimmingCount() == 18000, "disabled dimming does not count");

    PSC::Settings settings = PSC::current();
    settings.screenSaverMode = 0;
    PSC::set(settings, nullptr);
    VIEnableDimming(TRUE);
    retrace(2);
    check(VIGetDimmingCount() == 18000, "SC screen saver off keeps dimming disabled");
    PSC::reset();
}

void testMisuse() {
    check(aborts([] { PVI::signalRetrace(); }), "signalRetrace from an OS thread aborts");
    check(aborts([] {
              std::thread host([] { VIWaitForRetrace(); });
              host.join();
          }),
          "VIWaitForRetrace from interrupt context aborts");
    check(aborts([] { PVI::setClock(PVI::Clock::Internal); }), "changing the clock after VIInit aborts");
}

void testRealtimeClock() {
    PVI::shutdown();
    PVI::setClock(PVI::Clock::Internal);
    VIInit();
    // Functional: every VIWaitForRetrace returns only after a new retrace.
    // How many retraces pass during one call depends on when the host
    // schedules the woken thread (more than one under load), so the clock
    // rate is measured as retraces counted over elapsed time, which the
    // retrace thread's absolute schedule keeps accurate either way.
    VIWaitForRetrace();
    const auto start = std::chrono::steady_clock::now();
    const u32 first = VIGetRetraceCount();
    bool eachAdvanced = true;
    for (int i = 0; i < 30; ++i) {
        const u32 before = VIGetRetraceCount();
        VIWaitForRetrace();
        eachAdvanced = eachAdvanced && VIGetRetraceCount() > before;
    }
    const u32 counted = VIGetRetraceCount() - first;
    const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    check(eachAdvanced && counted >= 30, "each VIWaitForRetrace waits for a new retrace");
    const double rate = counted / seconds;
    if (rate < 54.0 || rate > 66.0) {
        std::fprintf(stderr, "internal clock: %u retraces in %.3f s\n", counted, seconds);
    }
    check(rate > 54.0 && rate < 66.0, "internal clock runs at about 59.94 Hz");

    const GXRenderModeObj pal = renderMode(VI_TVMODE_PAL_INT, 640, 528);
    VIConfigure(&pal);
    VIFlush();
    VIWaitForRetrace();
    VIWaitForRetrace();  // the PAL mode is latched at the first
    const auto palStart = std::chrono::steady_clock::now();
    const u32 palFirst = VIGetRetraceCount();
    for (int i = 0; i < 25; ++i) {
        VIWaitForRetrace();
    }
    const u32 palCounted = VIGetRetraceCount() - palFirst;
    const double palSeconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - palStart).count();
    const double palRate = palCounted / palSeconds;
    if (palRate < 45.0 || palRate > 55.0) {
        std::fprintf(stderr, "PAL clock: %u retraces in %.3f s\n", palCounted, palSeconds);
    }
    check(PVI::displayState().fieldRate == 50.0 && palRate > 45.0 && palRate < 55.0, "internal clock follows PAL at 50 Hz");
    PVI::shutdown();
    check(PVI::displayState().retraceCount == 0, "shutdown resets VI");
}

// Display sync (petari/display_sync.hpp): which displays the retraces follow, and on which refresh
// the next one comes. Ticks are nanoseconds here.
void testDisplaySync() {
    namespace Sync = PetariNative::DisplaySync;
    const double ntsc = 60000.0 / 1001.0;
    const std::uint64_t hz120 = 8333333, hz60 = 16666667, hz144 = 6944444, hz75 = 13333333;
    check(Sync::refreshesPerRetrace(hz60, ntsc, 1e9) == 1 && Sync::refreshesPerRetrace(hz120, ntsc, 1e9) == 2 &&
              Sync::refreshesPerRetrace(16683333, ntsc, 1e9) == 1 && Sync::refreshesPerRetrace(4166667, ntsc, 1e9) == 4,
          "60, 120, 59.94 and 240 Hz displays are followed");
    check(Sync::refreshesPerRetrace(hz144, ntsc, 1e9) == 0 && Sync::refreshesPerRetrace(hz75, ntsc, 1e9) == 0 &&
              Sync::refreshesPerRetrace(0, ntsc, 1e9) == 0 && Sync::refreshesPerRetrace(hz60, 50.0, 1e9) == 0,
          "144 and 75 Hz displays, an unknown period and PAL at 60 Hz keep the timer");
    const std::uint64_t refresh = 1000000000;
    check(Sync::nextRetrace(refresh, hz120, refresh, ntsc, 1e9) == refresh + 2 * hz120,
          "at 120 Hz every second refresh after the last retrace");
    check(Sync::nextRetrace(refresh, hz120, refresh - 2 * hz120 + 300000, ntsc, 1e9) == refresh,
          "a retrace woken a little late still takes the refresh after it");
    check(Sync::nextRetrace(refresh, hz60, refresh - 3 * hz60, ntsc, 1e9) == refresh,
          "after a stall the next refresh, not a burst");
    check(Sync::nextRetrace(refresh, hz144, refresh, ntsc, 1e9) == 0, "no refresh to follow at 144 Hz");

    // Reported refreshes scatter by up to a millisecond; the kept grid stays within a fraction of it.
    Sync::refreshTicks.store(0);
    Sync::refreshCount.store(0);
    const long scatter[] = {800000, -700000, 300000, -900000, 600000, -200000, 900000, -800000};
    std::uint64_t worst = 0;
    for (int i = 0; i < 400; i++) {
        const std::uint64_t grid = refresh + static_cast<std::uint64_t>(i) * hz120;
        Sync::noteRefresh(grid + scatter[i % 8], hz120);
        const std::uint64_t kept = Sync::refreshTicks.load();
        if (i > 50) worst = std::max(worst, kept > grid ? kept - grid : grid - kept);
    }
    check(worst < 200000 && Sync::refreshCount.load() == 400, "the kept refresh grid smooths the reports' scatter");
    Sync::noteRefresh(refresh + 402 * hz120 + 100000, hz120);
    check(Sync::refreshCount.load() == 403, "a missed report still counts its refresh");
    Sync::refreshShowing(refresh);  // before the grid: no crash
    check(Sync::refreshShowing(Sync::refreshTicks.load() + hz120 / 2) == 404, "a present between refreshes is shown on the next");
    Sync::refreshTicks.store(0);
    Sync::refreshCount.store(0);
}

}  // namespace

int main() {
    __OSThreadInit();
    testExternalClockLatching();
    testWaitForRetraceOnOsThreads();
    testDimming();
    testMisuse();
    testRealtimeClock();
    testDisplaySync();
    OSReport("platform VI tests passed (%d checks)\n", checks);
    return 0;
}

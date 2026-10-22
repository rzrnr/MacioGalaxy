// Display sync (display_link.hpp).

#include "display_link.hpp"

#include "petari/display_sync.hpp"

#include <CoreGraphics/CoreGraphics.h>
#include <CoreVideo/CoreVideo.h>
#include <mach/mach_time.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>

// CVDisplayLink is deprecated since macOS 15 in favour of CADisplayLink, which needs an
// NSView or NSScreen and a run loop; this C API still reports a display's refreshes.
#pragma clang diagnostic ignored "-Wdeprecated-declarations"

namespace PetariNative::App::DisplayLink {
namespace {

CVDisplayLinkRef gLink = nullptr;  // game thread
CGDirectDisplayID gDisplay = 0;    // game thread; 0: no link

// Cadence counts (game thread): how many refreshes each frame stayed on screen, from the refresh
// each present lands on (DisplaySync::refreshShowing).
std::uint64_t gLastShown = 0;
std::uint64_t gHeldCounts[4] = {};  // 1, 2, 3, 4 or more refreshes
std::uint64_t gReplaced = 0;        // replaced by a later present before its refresh
std::uint64_t gPresentCount = 0;
// The intervals between presents, in half milliseconds up to 50 ms, for the report's percentiles:
// the frame times the stats overlay shows.
std::uint64_t gIntervalBins[101] = {};
std::uint64_t gLastPresentTicks = 0;
std::atomic<std::uint64_t> gRefreshes{0};

double ticksPerSecond() {
    static const double ticks = [] {
        mach_timebase_info_data_t timebase;
        mach_timebase_info(&timebase);
        return 1e9 * timebase.denom / timebase.numer;
    }();
    return ticks;
}

CVReturn onRefresh(CVDisplayLinkRef link, const CVTimeStamp* now, const CVTimeStamp*, CVOptionFlags, CVOptionFlags*, void*) {
    double seconds = now->videoTimeScale > 0 && now->videoRefreshPeriod > 0
                         ? static_cast<double>(now->videoRefreshPeriod) / static_cast<double>(now->videoTimeScale)
                         : CVDisplayLinkGetActualOutputVideoRefreshPeriod(link);
    if (seconds > 0.0 && seconds < 0.1) {
        DisplaySync::noteRefresh(now->hostTime, static_cast<std::uint64_t>(seconds * ticksPerSecond()));
    }

    gRefreshes.fetch_add(1, std::memory_order_relaxed);
    return kCVReturnSuccess;
}

void stop() {
    DisplaySync::enabled.store(false, std::memory_order_relaxed);
    if (gLink != nullptr) {
        CVDisplayLinkStop(gLink);
        CVDisplayLinkRelease(gLink);
        gLink = nullptr;
    }
    gDisplay = 0;
}

}  // namespace

void follow(SDL_Window* window, bool sync) {
    CGDirectDisplayID display = 0;
    if (window != nullptr) {
        // SDL's window coordinates are global display points with the origin at the top
        // left of the main display, as CoreGraphics' are.
        int x = 0, y = 0, width = 0, height = 0;
        SDL_GetWindowPosition(window, &x, &y);
        SDL_GetWindowSize(window, &width, &height);
        std::uint32_t count = 0;
        const CGPoint centre = CGPointMake(x + width / 2.0, y + height / 2.0);
        if (CGGetDisplaysWithPoint(centre, 1, &display, &count) != kCGErrorSuccess || count == 0) {
            display = 0;
        }
    }
    if (display == gDisplay) {
        DisplaySync::enabled.store(sync && gLink != nullptr, std::memory_order_relaxed);
        return;
    }
    stop();
    if (display == 0) {
        return;
    }
    if (CVDisplayLinkCreateWithCGDisplay(display, &gLink) != kCVReturnSuccess ||
        CVDisplayLinkSetOutputCallback(gLink, onRefresh, nullptr) != kCVReturnSuccess || CVDisplayLinkStart(gLink) != kCVReturnSuccess) {
        std::fprintf(stderr, "Petari display sync: no display link for display %u; the game keeps its own 59.94 Hz clock\n", display);
        if (gLink != nullptr) {
            CVDisplayLinkRelease(gLink);
            gLink = nullptr;
        }
        return;
    }
    gDisplay = display;
    DisplaySync::enabled.store(sync, std::memory_order_relaxed);
}

void notePresent() {
    const std::uint64_t now = mach_absolute_time();
    if (gLastPresentTicks != 0) {
        const double ms = static_cast<double>(now - gLastPresentTicks) * 1e3 / ticksPerSecond();
        ++gIntervalBins[std::min<int>(static_cast<int>(ms * 2.0), 100)];
    }
    gLastPresentTicks = now;
    const std::uint64_t shown = DisplaySync::refreshShowing(now);
    if (shown == 0 || gLink == nullptr) {
        gLastShown = 0;
        return;
    }
    ++gPresentCount;
    if (gLastShown != 0) {
        if (shown <= gLastShown) {
            ++gReplaced;
        } else {
            ++gHeldCounts[std::min<std::uint64_t>(shown - gLastShown, 4) - 1];
        }
    }
    gLastShown = std::max(shown, gLastShown);
}

void writeReport() {
    std::uint64_t intervals = 0;
    for (const std::uint64_t bin : gIntervalBins) {
        intervals += bin;
    }
    if (intervals > 0) {
        const auto percentile = [&](double share) {
            std::uint64_t seen = 0;
            for (int i = 0; i <= 100; i++) {
                seen += gIntervalBins[i];
                if (seen >= share * intervals) {
                    return i * 0.5 + 0.25;
                }
            }
            return 50.0;
        };
        int longest = 100;
        while (longest > 0 && gIntervalBins[longest] == 0) {
            --longest;
        }
        std::fprintf(stderr, "Petari present intervals: %llu; median %.2f ms, 95%% %.2f ms, 99%% %.2f ms, longest %s%.1f ms\n",
                     static_cast<unsigned long long>(intervals), percentile(0.5), percentile(0.95), percentile(0.99),
                     longest == 100 ? "over " : "", longest * 0.5 + (longest == 100 ? 0.0 : 0.5));
    }
    const std::uint64_t refreshes = gRefreshes.load(std::memory_order_relaxed);
    if (refreshes == 0) {
        return;
    }
    std::fprintf(stderr,
                 "Petari display: %llu refreshes, %llu retraces on a refresh, %llu presents; frames on screen for 1 refresh %llu, "
                 "2: %llu, 3: %llu, 4 or more: %llu; replaced before their refresh: %llu\n",
                 static_cast<unsigned long long>(refreshes),
                 static_cast<unsigned long long>(DisplaySync::syncedRetraces.load(std::memory_order_relaxed)),
                 static_cast<unsigned long long>(gPresentCount), static_cast<unsigned long long>(gHeldCounts[0]),
                 static_cast<unsigned long long>(gHeldCounts[1]), static_cast<unsigned long long>(gHeldCounts[2]),
                 static_cast<unsigned long long>(gHeldCounts[3]), static_cast<unsigned long long>(gReplaced));
}

}  // namespace PetariNative::App::DisplayLink

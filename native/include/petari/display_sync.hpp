#pragma once
// Display sync (V-Sync on the Graphics page, native/FRAME_RATE.md): a display link
// (native/app/display_link.cpp) reports every refresh of the game window's display, and
// the VI retrace clock (native/platform/vi/vi_host.cpp) raises its retraces on those
// refreshes instead of on its own 59.94 Hz timer. Every game frame then meets the
// display the same way; a free-running clock drifts against the display's refreshes and
// every few seconds puts frames unevenly on screen.
//
// Only a display at a multiple of the field rate is followed (60 Hz, 120 Hz, 59.94 Hz,
// 240 Hz for NTSC); at another rate (75, 144 Hz) the clock keeps its own timer. Without a
// refresh report for 100 ms (the link stopped) it does the same.
//
// Header-only (C++17 inline variables), as petari/frame_telemetry.hpp: every static
// library that includes it shares one copy in the executable, without a link dependency.
// Times are mach_absolute_time ticks.

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdint>

namespace PetariNative::DisplaySync {

inline std::atomic<bool> enabled{false};              // V-Sync on; the display link runs
inline std::atomic<std::uint64_t> refreshTicks{0};    // the latest refresh
inline std::atomic<std::uint64_t> periodTicks{0};     // between refreshes
inline std::atomic<bool> synced{false};               // the latest retrace was raised on a refresh
inline std::atomic<int> every{0};                     // refreshes per retrace while synced
inline std::atomic<std::uint64_t> refreshCount{0};    // refreshes reported so far, the latest included
inline std::atomic<std::uint64_t> syncedRetraces{0};  // retraces raised on a refresh, for the report

// The display link thread, at every refresh. The display refreshes on a regular grid, but the
// reported times scatter around it (a quarter millisecond on average, up to almost one on an
// M3 Pro's 120 Hz display): each report moves the kept grid a sixteenth of the way to it.
inline void noteRefresh(std::uint64_t refresh, std::uint64_t period) {
    const std::uint64_t last = refreshTicks.load(std::memory_order_relaxed);
    std::uint64_t kept = refresh;
    std::uint64_t refreshes = 1;
    if (last != 0 && period != 0 && refresh > last) {
        refreshes = (refresh - last + period / 2) / period;
        if (refreshes >= 1 && refreshes <= 4) {
            const std::uint64_t predicted = last + refreshes * period;
            kept = refresh >= predicted ? predicted + (refresh - predicted) / 16 : predicted - (predicted - refresh) / 16;
        } else {
            refreshes = std::max<std::uint64_t>(refreshes, 1);  // after a gap: start the grid again
        }
    }
    periodTicks.store(period, std::memory_order_relaxed);
    refreshCount.fetch_add(refreshes, std::memory_order_relaxed);
    refreshTicks.store(kept, std::memory_order_release);
}

// The refresh that shows a frame presented at time t: the first after it, counted as refreshCount
// counts them (FIFO and a frame ready in time; without V-Sync the newest frame before a refresh).
inline std::uint64_t refreshShowing(std::uint64_t t) {
    const std::uint64_t refresh = refreshTicks.load(std::memory_order_acquire);
    const std::uint64_t count = refreshCount.load(std::memory_order_relaxed);
    const std::uint64_t period = periodTicks.load(std::memory_order_relaxed);
    if (period == 0 || refresh == 0) {
        return 0;
    }
    if (t < refresh) {
        const std::uint64_t back = (refresh - t) / period;  // refreshes since t, the latest excluded
        return count > back ? count - back : 0;
    }
    return count + (t - refresh) / period + 1;
}

// Refreshes per retrace when the display runs at a multiple of fieldRate (within 1%), else 0.
inline int refreshesPerRetrace(std::uint64_t period, double fieldRate, double ticksPerSecond) {
    if (period == 0 || fieldRate <= 0.0) {
        return 0;
    }
    const double refreshRate = ticksPerSecond / static_cast<double>(period);
    const long every = std::lround(refreshRate / fieldRate);
    if (every < 1 || every > 8 || std::fabs(refreshRate / static_cast<double>(every) - fieldRate) > fieldRate * 0.01) {
        return 0;
    }
    return static_cast<int>(every);
}

// The next retrace on a refresh: the first refresh (refresh + n periods) at or after half a
// refresh before the regular spacing from the previous retrace, so that jitter in the reports
// never skips or doubles one. 0 when the display is no multiple of the field rate.
inline std::uint64_t nextRetrace(std::uint64_t refresh, std::uint64_t period, std::uint64_t previousRetrace, double fieldRate,
                                 double ticksPerSecond) {
    const int every = refreshesPerRetrace(period, fieldRate, ticksPerSecond);
    if (every == 0) {
        return 0;
    }
    const std::uint64_t earliest = previousRetrace + static_cast<std::uint64_t>(every) * period - period / 2;
    std::uint64_t deadline = refresh;
    if (earliest > deadline) {
        deadline += (earliest - deadline + period - 1) / period * period;
    }
    return deadline;
}

}  // namespace PetariNative::DisplaySync

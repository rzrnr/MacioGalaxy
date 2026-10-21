#pragma once
// The Graphics page of the F1 menu (native/GRAPHICS.md): the game image's render
// resolution, the filter that scales it to the window (FSR 1, bicubic, bilinear),
// sharpening, FXAA, and the stats overlay.
//
// graphics.txt in the user directory; a missing file keeps the defaults, which
// draw as before (the display's resolution, no sharpening, no FXAA, no stats).
// PETARI_GRAPHICS overrides the file for one run, e.g.
// PETARI_GRAPHICS=Resolution=1080,Upscaler=bicubic. Settings are atomics: the menu
// writes them on a game thread, the frame seam and the present pass read them.

#include <filesystem>
#include <string>

namespace PetariNative::Graphics {

// Resolution: the render height in lines, the same on every display. Display
// (0) renders at the displayed image's own size. Below the displayed size the
// image is upscaled; above it, it is supersampled (shrunk with an area filter).
constexpr int kDisplay = 0;
constexpr int kResolutions[] = {kDisplay, 480, 720, 1080, 1440, 2160};
constexpr int kResolutionCount = static_cast<int>(sizeof(kResolutions) / sizeof(kResolutions[0]));

// The filter while the render resolution is below the displayed size.
enum class Upscaler : int { Fsr1, Bicubic, Bilinear, Count };
// FSR 1's RCAS sharpening after scaling, at any resolution.
enum class Sharpening : int { Off, Low, Medium, High, Count };
enum class Stats : int { Off, Fps, Detailed, Count };
// V-Sync (native/FRAME_RATE.md): Off, frames at once on the game's own clock; On, the clock
// follows the display and each frame waits for its refresh; LowLatency, as On, with the clock
// moved as close to the refreshes as the frames' draw times allow; Variable, on a ProMotion or
// Adaptive-Sync display in fullscreen the display follows the game's clock (elsewhere as On).
enum class VSync : int { Off, On, LowLatency, Variable, Count };

// FrameRate: 60, or 120 with an extra, interpolated frame between two game steps (native/FRAME_RATE.md).
constexpr int kFrameRates[] = {60, 120};

struct Settings {
    int frameRate = 60;         // one of kFrameRates
    VSync vsync = VSync::On;
    int resolution = kDisplay;  // one of kResolutions
    Upscaler upscaler = Upscaler::Fsr1;
    Sharpening sharpening = Sharpening::Off;
    bool fxaa = false;
    Stats stats = Stats::Off;
};

// The choice in kResolutions nearest to a height (0 and below: Display).
constexpr int nearestResolution(int height) {
    if (height <= 0) return kDisplay;
    int best = kResolutions[1];
    for (int i = 1; i < kResolutionCount; i++) {
        const int distance = kResolutions[i] > height ? kResolutions[i] - height : height - kResolutions[i];
        const int bestDistance = best > height ? best - height : height - best;
        if (distance < bestDistance) best = kResolutions[i];
    }
    return best;
}

// The render size for a displayed image of outputWidth x outputHeight pixels:
// the chosen height, the width at the image's aspect.
inline void renderSize(int resolution, int outputWidth, int outputHeight, int* width, int* height) {
    if (resolution == kDisplay || outputWidth <= 0 || outputHeight <= 0) {
        *width = outputWidth;
        *height = outputHeight;
        return;
    }
    *height = resolution;
    *width = static_cast<int>(static_cast<long long>(outputWidth) * resolution * 2 / outputHeight + 1) / 2;
}

// RCAS's sharpness, linear 0..1 (AMD's "stops" of reduction: Low 1, Medium 0.5, High 0.2).
inline float sharpness(Sharpening sharpening) {
    switch (sharpening) {
    case Sharpening::Low: return 0.5f;
    case Sharpening::Medium: return 0.7071f;
    case Sharpening::High: return 0.8706f;
    default: return 0.0f;
    }
}

// Menu and stats labels.
inline const char* resolutionName(int resolution) {
    switch (resolution) {
    case 480: return "480p (Wii)";
    case 720: return "720p";
    case 1080: return "1080p";
    case 1440: return "1440p";
    case 2160: return "4K";
    default: return "Display";
    }
}
inline const char* upscalerName(Upscaler upscaler) {
    return upscaler == Upscaler::Bilinear ? "Bilinear" : upscaler == Upscaler::Bicubic ? "Bicubic" : "FSR 1";
}
inline const char* sharpeningName(Sharpening sharpening) {
    return sharpening == Sharpening::Low ? "Low" : sharpening == Sharpening::Medium ? "Medium" : sharpening == Sharpening::High ? "High" : "Off";
}
inline const char* vsyncName(VSync vsync) {
    return vsync == VSync::Off ? "Off" : vsync == VSync::LowLatency ? "Low latency" : vsync == VSync::Variable ? "Variable" : "On";
}
inline const char* statsName(Stats stats) {
    return stats == Stats::Fps ? "FPS" : stats == Stats::Detailed ? "Detailed" : "Off";
}

Settings current();  // any thread
void set(const Settings& settings);  // any thread; the resolution is snapped to kResolutions

bool load(const std::filesystem::path& file, std::string* error);  // then PETARI_GRAPHICS
bool save(std::string* error);  // no-op before load
std::string serialize();
bool parse(const std::string& text, std::string* error);  // nothing changes on error

// The displayed game image in pixels, from the frame seam; 0 before the first frame. Any thread.
void setOutputSize(int width, int height);
void outputSize(int* width, int* height);

// Frame interpolation over the last second (native/FRAME_RATE.md), from the frame seam, for the
// Graphics page and the stats. Any thread.
struct FrameRateStatus {
    int displayHz = 0;             // the game window's display; 0: unknown
    bool variableRefresh = false;  // the display follows the game (V-Sync Variable in effect)
    int interpolatedPercent = -1;  // game steps with an extra frame; -1: no step asked for one
    int latePercent = 0;           // game steps presented too late for one
};
void setFrameRateStatus(const FrameRateStatus& status);
FrameRateStatus frameRateStatus();

void resetForTesting();

}  // namespace PetariNative::Graphics

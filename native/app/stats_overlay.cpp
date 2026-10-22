// The stats overlay (stats_overlay.hpp), drawn with Dear ImGui's foreground list so it
// never takes input, in the F1 menu's colours.

#include "stats_overlay.hpp"

#include "petari/graphics.hpp"
#include "petari/home_menu.hpp"

#include <imgui.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>

namespace PetariNative::App::StatsOverlay {
namespace {

using Clock = std::chrono::steady_clock;

constexpr int kHistory = 180;          // game steps kept: where the step's time goes
constexpr int kPresents = 360;         // presents kept: the graph and the worst frame time (3 s at 120)
constexpr double kAverageMs = 1000.0;  // frames per second and the averages, over the last second
constexpr double kGraphTopMs = 1000.0 / 30.0;
constexpr const char* kTitle = "Super Mario Galaxy";

Sample gSamples[kHistory];
int gCount = 0;
int gNext = 0;

double gIntervals[kPresents];  // milliseconds between presents
int gIntervalCount = 0;
int gIntervalNext = 0;
Clock::time_point gLastPresent;
bool gPresented = false;

// The texts change four times a second, so they can be read.
Clock::time_point gTextTime;
char gFps[32] = "";
char gTimes[96] = "";
char gParts[128] = "";
char gRender[128] = "";
char gInterpolation[96] = "";  // at Frame rate 120: how many steps get an extra frame, or why none
bool gFresh = false;

Clock::time_point gTitleTime;
bool gTitleShown = false;  // the title carries the frames per second

const Sample& sample(int age) {  // 0: the newest
    const int back = std::clamp(age, 0, kHistory - 1);
    return gSamples[(gNext - 1 - back + kHistory) % kHistory];  // audit-ok: gNext < kHistory and back < kHistory, so 0 <= index < kHistory
}

double interval(int age) {  // 0: the newest
    const int back = std::clamp(age, 0, kPresents - 1);
    return gIntervals[(gIntervalNext - 1 - back + kPresents) % kPresents];  // audit-ok: gIntervalNext < kPresents and back < kPresents
}

ImU32 color(float r, float g, float b, float a) {
    return ImGui::ColorConvertFloat4ToU32(ImVec4(r, g, b, a));
}

void refreshTexts(int outputWidth, int outputHeight) {
    // Frames per second and frame times from the presents, extra frames included.
    double sum = 0.0, worst = 0.0;
    int frames = 0;
    for (int age = 0; age < gIntervalCount; age++) {
        worst = std::max(worst, interval(age));
        if (sum < kAverageMs) {
            sum += interval(age);
            frames++;
        }
    }
    // Where a game step's time goes, over the last second of steps.
    double stepSum = 0.0, work = 0.0, drawDone = 0.0, present = 0.0;
    int steps = 0;
    for (int age = 0; age < gCount && stepSum < kAverageMs; age++) {
        const Sample& s = sample(age);
        stepSum += s.intervalMs;
        work += s.workMs;
        drawDone += s.drawDoneMs;
        present += s.presentMs;
        steps++;
    }
    const double fps = sum > 0.0 ? frames * 1000.0 / sum : 0.0;
    const double n = steps > 0 ? steps : 1;
    std::snprintf(gFps, sizeof(gFps), "%.0f FPS", fps);
    std::snprintf(gTimes, sizeof(gTimes), "Frame %.1f ms   worst %.1f ms", frames > 0 ? sum / frames : 0.0, worst);
    std::snprintf(gParts, sizeof(gParts), "Game %.1f ms   GPU wait %.1f ms   present %.1f ms", work / n, drawDone / n, present / n);
    namespace Graphics = PetariNative::Graphics;
    const Graphics::Settings settings = Graphics::current();
    int width = 0, height = 0;
    Graphics::renderSize(settings.resolution, outputWidth, outputHeight, &width, &height);
    const char* filter = height < outputHeight ? Graphics::upscalerName(settings.upscaler) : height > outputHeight ? "Area" : "1:1";
    char sharpen[32] = "";
    if (settings.sharpening != Graphics::Sharpening::Off) {
        std::snprintf(sharpen, sizeof(sharpen), "   sharpen %s", Graphics::sharpeningName(settings.sharpening));
    }
    std::snprintf(gRender, sizeof(gRender), "%d x %d -> %d x %d   %s%s%s", width, height, outputWidth, outputHeight, filter, sharpen,
                  settings.fxaa ? "   FXAA" : "");
    gInterpolation[0] = '\0';
    if (settings.frameRate >= 120) {
        const Graphics::FrameRateStatus status = Graphics::frameRateStatus();
        if (status.displayHz > 0 && status.displayHz < 100) {
            std::snprintf(gInterpolation, sizeof(gInterpolation), "120: no extra frames on this %d Hz display", status.displayHz);
        } else if (status.interpolatedPercent < 0) {
            std::snprintf(gInterpolation, sizeof(gInterpolation), "120: no extra frames here");
        } else {
            std::snprintf(gInterpolation, sizeof(gInterpolation), "Extra frames %d%%   too late %d%%", status.interpolatedPercent,
                          status.latePercent);
        }
    }
}

void updateTitle(SDL_Window* window, bool show) {
    if (window == nullptr || (!show && !gTitleShown)) {
        return;
    }
    const Clock::time_point now = Clock::now();
    if (show && gTitleShown && now - gTitleTime < std::chrono::milliseconds(500)) {
        return;
    }
    gTitleTime = now;
    gTitleShown = show;
    char title[64];
    if (show) {
        std::snprintf(title, sizeof(title), "%s - %s", kTitle, gFps);
    } else {
        std::snprintf(title, sizeof(title), "%s", kTitle);
    }
    SDL_SetWindowTitle(window, title);
}

// The last kPresents frame times, 0..kGraphTopMs, with lines at 60 and 120 frames per second.
void drawGraph(ImDrawList* list, ImVec2 min, ImVec2 max, float line) {
    list->AddRectFilled(min, max, color(0.02f, 0.03f, 0.08f, 0.7f), (max.y - min.y) * 0.1f);
    for (const double fps : {60.0, 120.0}) {
        const float y = max.y - (max.y - min.y) * static_cast<float>(1000.0 / fps / kGraphTopMs);
        list->AddLine(ImVec2(min.x, y), ImVec2(max.x, y), color(0.55f, 0.65f, 0.95f, 0.45f), line);
    }
    ImVec2 points[kPresents];
    const int count = gIntervalCount;
    for (int i = 0; i < count; i++) {
        const double ms = std::min(interval(count - 1 - i), kGraphTopMs);
        const float x = min.x + (max.x - min.x) * static_cast<float>(i) / static_cast<float>(kPresents - 1);
        points[i] = ImVec2(x, max.y - (max.y - min.y) * static_cast<float>(ms / kGraphTopMs));
    }
    if (count > 1) {
        list->AddPolyline(points, count, color(0.98f, 0.80f, 0.22f, 0.95f), 0, line * 1.5f);
    }
}

}  // namespace

void addFrame(const Sample& s) {
    gSamples[gNext] = s;
    gNext = (gNext + 1) % kHistory;
    gCount = std::min(gCount + 1, kHistory);
    gFresh = true;
}

void notePresent() {
    const Clock::time_point now = Clock::now();
    if (gPresented) {
        gIntervals[gIntervalNext] = std::chrono::duration<double, std::milli>(now - gLastPresent).count();
        gIntervalNext = (gIntervalNext + 1) % kPresents;
        gIntervalCount = std::min(gIntervalCount + 1, kPresents);
    }
    gLastPresent = now;
    gPresented = true;
}

void draw(SDL_Window* window, float imageX, float imageY, float imageWidth, float imageHeight) {
    const float density = window != nullptr ? SDL_GetWindowPixelDensity(window) : 1.0f;
    const int outputWidth = static_cast<int>(std::lround(imageWidth * density));
    const int outputHeight = static_cast<int>(std::lround(imageHeight * density));
    PetariNative::Graphics::setOutputSize(outputWidth, outputHeight);

    const PetariNative::Graphics::Stats stats = PetariNative::Graphics::current().stats;
    const bool on = stats != PetariNative::Graphics::Stats::Off;
    const Clock::time_point now = Clock::now();
    if (on && gFresh && now - gTextTime >= std::chrono::milliseconds(250)) {
        gTextTime = now;
        refreshTexts(outputWidth, outputHeight);
    }
    updateTitle(window, on && gFps[0] != '\0');
    if (!on || gFps[0] == '\0' || !(imageWidth > 0.0f) || !(imageHeight > 0.0f) || ImGui::GetCurrentContext() == nullptr) {
        return;
    }

    ImDrawList* list = ImGui::GetForegroundDrawList();
    ImFont* font = ImGui::GetFont();
    list->PushClipRect(ImVec2(imageX, imageY), ImVec2(imageX + imageWidth, imageY + imageHeight), false);
    const float h = imageHeight;
    const float margin = h * 0.02f;
    const float line = std::max(1.0f, h * 0.0015f);
    const ImU32 text = color(0.92f, 0.94f, 1.0f, 0.97f);
    const ImU32 gold = color(0.98f, 0.80f, 0.22f, 1.0f);
    const ImU32 panelFill = color(0.06f, 0.08f, 0.16f, 0.82f);
    const ImU32 panelBorder = color(0.55f, 0.65f, 0.95f, 0.6f);
    // Top centre, where the game's counters leave room; top left while the F1 menu's
    // panel takes the centre (the counters are dimmed behind it).
    const bool menu = PetariNative::HomeMenu::publishedView().visible;
    const auto left = [&](float width) { return menu ? imageX + margin : imageX + (imageWidth - width) * 0.5f; };

    if (stats == PetariNative::Graphics::Stats::Fps) {
        const float size = h * 0.03f;
        const ImVec2 extent = font->CalcTextSizeA(size, 1.0e9f, 0.0f, gFps);
        const float padX = size * 0.6f, padY = size * 0.3f;
        const ImVec2 origin(left(extent.x + padX * 2.0f), imageY + margin);
        const ImVec2 max(origin.x + extent.x + padX * 2.0f, origin.y + extent.y + padY * 2.0f);
        list->AddRectFilled(origin, max, panelFill, (max.y - origin.y) * 0.5f);
        list->AddRect(origin, max, panelBorder, (max.y - origin.y) * 0.5f, 0, line);
        list->AddText(font, size, ImVec2(origin.x + padX, origin.y + padY), gold, gFps);
        list->PopClipRect();
        return;
    }

    const float shrink = menu ? 0.8f : 1.0f;  // clear of the menu's panel
    const float big = h * 0.034f * shrink;
    const float small = h * 0.022f * shrink;
    const float pad = small * 0.8f;
    const bool interpolation = gInterpolation[0] != '\0';
    const float width = std::max({font->CalcTextSizeA(small, 1.0e9f, 0.0f, gParts).x, font->CalcTextSizeA(small, 1.0e9f, 0.0f, gRender).x,
                                  font->CalcTextSizeA(small, 1.0e9f, 0.0f, gTimes).x,
                                  font->CalcTextSizeA(small, 1.0e9f, 0.0f, gInterpolation).x}) +
                        pad * 2.0f;
    const float graphHeight = h * 0.07f * shrink;
    const float height = pad * 2.0f + big + small * 3.0f + graphHeight + small * 1.6f + (interpolation ? small * 1.2f : 0.0f);
    const ImVec2 origin(left(width), imageY + margin);
    const ImVec2 max(origin.x + width, origin.y + height);
    list->AddRectFilled(origin, max, panelFill, h * 0.012f);
    list->AddRect(origin, max, panelBorder, h * 0.012f, 0, line);
    float y = origin.y + pad;
    list->AddText(font, big, ImVec2(origin.x + pad, y), gold, gFps);
    y += big + small * 0.2f;
    list->AddText(font, small, ImVec2(origin.x + pad, y), text, gTimes);
    y += small * 1.3f;
    drawGraph(list, ImVec2(origin.x + pad, y), ImVec2(max.x - pad, y + graphHeight), line);
    y += graphHeight + small * 0.4f;
    list->AddText(font, small, ImVec2(origin.x + pad, y), text, gParts);
    y += small * 1.2f;
    list->AddText(font, small, ImVec2(origin.x + pad, y), color(0.78f, 0.82f, 0.92f, 0.97f), gRender);
    if (interpolation) {
        y += small * 1.2f;
        list->AddText(font, small, ImVec2(origin.x + pad, y), color(0.78f, 0.82f, 0.92f, 0.97f), gInterpolation);
    }
    list->PopClipRect();
}

}  // namespace PetariNative::App::StatsOverlay

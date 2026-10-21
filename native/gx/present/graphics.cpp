// The Graphics page's settings (petari/graphics.hpp).

#include <petari/graphics.hpp>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstdlib>
#include <fstream>
#include <mutex>
#include <sstream>

namespace PetariNative::Graphics {
namespace {

std::atomic<int> gFrameRate{60};
std::atomic<int> gResolution{kDisplay};
std::atomic<int> gUpscaler{static_cast<int>(Upscaler::Fsr1)};
std::atomic<int> gSharpening{static_cast<int>(Sharpening::Off)};
std::atomic<bool> gFxaa{false};
std::atomic<int> gStats{static_cast<int>(Stats::Off)};
std::atomic<int> gOutputWidth{0};
std::atomic<int> gOutputHeight{0};
std::atomic<int> gDisplayHz{0};
std::atomic<int> gInterpolatedPercent{-1};
std::atomic<int> gLatePercent{0};
std::mutex gStoreLock;
std::filesystem::path gStore;  // under gStoreLock; empty before load

std::string trim(const std::string& text) {
    const auto first = text.find_first_not_of(" \t\r");
    if (first == std::string::npos) return {};
    const auto last = text.find_last_not_of(" \t\r");
    return text.substr(first, last - first + 1);
}

std::string lower(std::string text) {
    std::transform(text.begin(), text.end(), text.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return text;
}

// "display", a height ("1080", "1080p") or "4k"; -1 if none.
int parseResolution(const std::string& value) {
    if (value == "display") return kDisplay;
    if (value == "4k") return 2160;
    std::string digits = value;
    if (!digits.empty() && digits.back() == 'p') digits.pop_back();
    char* end = nullptr;
    const long height = std::strtol(digits.c_str(), &end, 10);
    if (digits.empty() || end == nullptr || *end != '\0' || height < 240 || height > 4320) return -1;
    return nearestResolution(static_cast<int>(height));
}

// One "Key=value" line into settings; false with a message on a bad value.
bool parseLine(const std::string& key, const std::string& value, Settings* settings, std::string* message) {
    const std::string v = lower(value);
    if (key == "FrameRate") {
        if (v != "60" && v != "120") {
            *message = "FrameRate must be 60 or 120";
            return false;
        }
        settings->frameRate = v == "120" ? 120 : 60;
    } else if (key == "Resolution") {
        const int resolution = parseResolution(v);
        if (resolution < 0) {
            *message = "Resolution must be display, 480, 720, 1080, 1440 or 2160";
            return false;
        }
        settings->resolution = resolution;
    } else if (key == "Upscaler") {
        if (v != "fsr1" && v != "bicubic" && v != "bilinear") {
            *message = "Upscaler must be fsr1, bicubic or bilinear";
            return false;
        }
        settings->upscaler = v == "bilinear" ? Upscaler::Bilinear : v == "bicubic" ? Upscaler::Bicubic : Upscaler::Fsr1;
    } else if (key == "Sharpening") {
        if (v != "off" && v != "low" && v != "medium" && v != "high") {
            *message = "Sharpening must be off, low, medium or high";
            return false;
        }
        settings->sharpening = v == "low" ? Sharpening::Low : v == "medium" ? Sharpening::Medium : v == "high" ? Sharpening::High : Sharpening::Off;
    } else if (key == "AntiAliasing") {
        if (v != "off" && v != "fxaa") {
            *message = "AntiAliasing must be off or fxaa";
            return false;
        }
        settings->fxaa = v == "fxaa";
    } else if (key == "Stats") {
        if (v != "off" && v != "fps" && v != "detailed") {
            *message = "Stats must be off, fps or detailed";
            return false;
        }
        settings->stats = v == "fps" ? Stats::Fps : v == "detailed" ? Stats::Detailed : Stats::Off;
    }
    return true;  // unknown keys are ignored
}

}  // namespace

Settings current() {
    Settings settings;
    settings.frameRate = gFrameRate.load(std::memory_order_relaxed);
    settings.resolution = gResolution.load(std::memory_order_relaxed);
    settings.upscaler = static_cast<Upscaler>(gUpscaler.load(std::memory_order_relaxed));
    settings.sharpening = static_cast<Sharpening>(gSharpening.load(std::memory_order_relaxed));
    settings.fxaa = gFxaa.load(std::memory_order_relaxed);
    settings.stats = static_cast<Stats>(gStats.load(std::memory_order_relaxed));
    return settings;
}

void set(const Settings& settings) {
    gFrameRate.store(settings.frameRate >= 120 ? 120 : 60, std::memory_order_relaxed);
    gResolution.store(nearestResolution(settings.resolution), std::memory_order_relaxed);
    gUpscaler.store(std::clamp(static_cast<int>(settings.upscaler), 0, static_cast<int>(Upscaler::Count) - 1),
                    std::memory_order_relaxed);
    gSharpening.store(std::clamp(static_cast<int>(settings.sharpening), 0, static_cast<int>(Sharpening::Count) - 1),
                      std::memory_order_relaxed);
    gFxaa.store(settings.fxaa, std::memory_order_relaxed);
    gStats.store(std::clamp(static_cast<int>(settings.stats), 0, static_cast<int>(Stats::Count) - 1), std::memory_order_relaxed);
}

std::string serialize() {
    const Settings settings = current();
    std::ostringstream out;
    out << "# Petari graphics settings (F1 -> Graphics; native/GRAPHICS.md)\n"
        << "FrameRate=" << settings.frameRate << "\n"
        << "Resolution=";
    if (settings.resolution == kDisplay) {
        out << "display";
    } else {
        out << settings.resolution;
    }
    out << "\n"
        << "Upscaler=" << (settings.upscaler == Upscaler::Bilinear ? "bilinear" : settings.upscaler == Upscaler::Bicubic ? "bicubic" : "fsr1")
        << "\n"
        << "Sharpening=" << lower(sharpeningName(settings.sharpening)) << "\n"
        << "AntiAliasing=" << (settings.fxaa ? "fxaa" : "off") << "\n"
        << "Stats=" << lower(statsName(settings.stats)) << "\n";
    return out.str();
}

bool parse(const std::string& text, std::string* error) {
    std::istringstream in(text);
    std::string line;
    Settings settings = current();
    int number = 0;
    while (std::getline(in, line)) {
        number++;
        line = trim(line);
        if (line.empty() || line[0] == '#') continue;
        const auto equals = line.find('=');
        if (equals == std::string::npos) continue;
        std::string message;
        if (!parseLine(trim(line.substr(0, equals)), trim(line.substr(equals + 1)), &settings, &message)) {
            if (error) *error = "line " + std::to_string(number) + ": " + message;
            return false;
        }
    }
    set(settings);
    return true;
}

bool load(const std::filesystem::path& file, std::string* error) {
    {
        std::lock_guard<std::mutex> guard(gStoreLock);
        gStore = file;
    }
    if (std::ifstream in(file); in) {
        std::ostringstream text;
        text << in.rdbuf();
        if (!parse(text.str(), error)) {
            if (error) *error = file.string() + ": " + *error;
            return false;
        }
    }
    if (const char* env = std::getenv("PETARI_GRAPHICS"); env != nullptr && env[0] != '\0') {
        std::string text = env;
        std::replace(text.begin(), text.end(), ',', '\n');
        if (!parse(text, error)) {
            if (error) *error = "PETARI_GRAPHICS: " + *error;
            return false;
        }
    }
    return true;
}

bool save(std::string* error) {
    std::lock_guard<std::mutex> guard(gStoreLock);
    if (gStore.empty()) return true;
    const std::filesystem::path temporary = gStore.string() + ".tmp";
    {
        std::ofstream out(temporary, std::ios::trunc);
        out << serialize();
        if (!out) {
            if (error) *error = "cannot write " + temporary.string();
            return false;
        }
    }
    std::error_code ec;
    std::filesystem::rename(temporary, gStore, ec);
    if (ec) {
        if (error) *error = "cannot replace " + gStore.string() + ": " + ec.message();
        return false;
    }
    return true;
}

void setOutputSize(int width, int height) {
    gOutputWidth.store(width, std::memory_order_relaxed);
    gOutputHeight.store(height, std::memory_order_relaxed);
}

void outputSize(int* width, int* height) {
    *width = gOutputWidth.load(std::memory_order_relaxed);
    *height = gOutputHeight.load(std::memory_order_relaxed);
}

void setFrameRateStatus(const FrameRateStatus& status) {
    gDisplayHz.store(status.displayHz, std::memory_order_relaxed);
    gInterpolatedPercent.store(status.interpolatedPercent, std::memory_order_relaxed);
    gLatePercent.store(status.latePercent, std::memory_order_relaxed);
}

FrameRateStatus frameRateStatus() {
    FrameRateStatus status;
    status.displayHz = gDisplayHz.load(std::memory_order_relaxed);
    status.interpolatedPercent = gInterpolatedPercent.load(std::memory_order_relaxed);
    status.latePercent = gLatePercent.load(std::memory_order_relaxed);
    return status;
}

void resetForTesting() {
    std::lock_guard<std::mutex> guard(gStoreLock);
    gStore.clear();
    set(Settings{});
    setOutputSize(0, 0);
    setFrameRateStatus(FrameRateStatus{});
}

}  // namespace PetariNative::Graphics

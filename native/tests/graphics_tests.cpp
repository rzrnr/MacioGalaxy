// The Graphics page's settings (petari/graphics.hpp): choices, graphics.txt, PETARI_GRAPHICS.
#include <petari/graphics.hpp>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <unistd.h>

namespace Graphics = PetariNative::Graphics;

namespace {

int checks = 0;

void check(bool condition, const char* label) {
    ++checks;
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", label);
        std::exit(1);
    }
}

std::string read(const std::filesystem::path& file) {
    std::ifstream in(file);
    return std::string(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
}

Graphics::Settings settings(int resolution, bool fxaa = false) {
    Graphics::Settings result;
    result.resolution = resolution;
    result.fxaa = fxaa;
    return result;
}

void testChoices() {
    Graphics::resetForTesting();
    const Graphics::Settings defaults = Graphics::current();
    check(defaults.frameRate == 60 && defaults.resolution == Graphics::kDisplay && defaults.upscaler == Graphics::Upscaler::Fsr1 &&
              defaults.sharpening == Graphics::Sharpening::Off && !defaults.fxaa && defaults.stats == Graphics::Stats::Off,
          "defaults draw as before: the display's resolution, no sharpening, no FXAA, no stats");
    static_assert(Graphics::nearestResolution(0) == 0 && Graphics::nearestResolution(-5) == 0 && Graphics::nearestResolution(500) == 480 &&
                  Graphics::nearestResolution(900) == 720 && Graphics::nearestResolution(1200) == 1080 &&
                  Graphics::nearestResolution(1600) == 1440 && Graphics::nearestResolution(4000) == 2160);
    Graphics::set(settings(1000));
    check(Graphics::current().resolution == 1080, "set snaps the resolution to a choice");
    check(std::string(Graphics::resolutionName(0)) == "Display" && std::string(Graphics::resolutionName(480)) == "480p (Wii)" &&
              std::string(Graphics::resolutionName(1080)) == "1080p" && std::string(Graphics::resolutionName(2160)) == "4K",
          "resolution names");
    int width = 0, height = 0;
    Graphics::renderSize(1080, 2560, 1440, &width, &height);
    check(width == 1920 && height == 1080, "1080p on a 2560 x 1440 image renders 1920 x 1080");
    Graphics::renderSize(480, 2560, 1440, &width, &height);
    check(width == 853 && height == 480, "480p keeps the image's aspect");
    Graphics::renderSize(Graphics::kDisplay, 3024, 1701, &width, &height);
    check(width == 3024 && height == 1701, "Display renders at the image's own size");
    check(Graphics::sharpness(Graphics::Sharpening::Off) == 0.0f && Graphics::sharpness(Graphics::Sharpening::Low) == 0.5f &&
              std::fabs(Graphics::sharpness(Graphics::Sharpening::High) - std::exp2(-0.2f)) < 1e-3f,
          "sharpness follows AMD's stops: off, 1, 0.5, 0.2");
}

void testParse() {
    Graphics::resetForTesting();
    std::string error;
    check(Graphics::parse("# comment\nOther=1\nPicture=77\nResolution = 1080p\nUpscaler=Bicubic\nSharpening=medium\n"
                          "AntiAliasing=fxaa\nStats=detailed\n",
                          &error),
          "a full file parses, values case-insensitively");
    const Graphics::Settings parsed = Graphics::current();
    check(parsed.resolution == 1080 && parsed.upscaler == Graphics::Upscaler::Bicubic && parsed.sharpening == Graphics::Sharpening::Medium &&
              parsed.fxaa && parsed.stats == Graphics::Stats::Detailed,
          "every key is read, unknown lines (and the old Picture key) are ignored");
    check(Graphics::parse("Resolution=4K\n", &error) && Graphics::current().resolution == 2160, "4K is 2160");
    check(Graphics::parse("FrameRate=120\n", &error) && Graphics::current().frameRate == 120 && !Graphics::parse("FrameRate=90\n", &error),
          "FrameRate is 60 or 120");
    check(Graphics::serialize().find("FrameRate=120\n") != std::string::npos, "FrameRate is written");
    check(Graphics::parse("FrameRate=60\n", &error), "back to 60");
    check(Graphics::current().vsync == Graphics::VSync::On && Graphics::parse("VSync=off\n", &error) &&
              Graphics::current().vsync == Graphics::VSync::Off && Graphics::serialize().find("VSync=off\n") != std::string::npos &&
              !Graphics::parse("VSync=maybe\n", &error) && Graphics::parse("VSync=lowlatency\n", &error) &&
              Graphics::current().vsync == Graphics::VSync::LowLatency && Graphics::parse("VSync=variable\n", &error) &&
              Graphics::serialize().find("VSync=variable\n") != std::string::npos && Graphics::parse("VSync=on\n", &error) &&
              Graphics::current().vsync == Graphics::VSync::On,
          "VSync is on by default; off, lowlatency, variable or on");
    check(Graphics::parse("Resolution=1000\n", &error) && Graphics::current().resolution == 1080, "another height takes the nearest choice");
    check(Graphics::parse("Resolution=display\n", &error) && Graphics::current().resolution == 0, "display");
    check(!Graphics::parse("Stats=fps\nResolution=huge\n", &error) && error.find("line 2") != std::string::npos &&
              Graphics::current().stats == Graphics::Stats::Detailed,
          "a bad resolution is refused with its line, nothing changes");
    check(!Graphics::parse("Resolution=100\n", &error) && !Graphics::parse("Upscaler=dlss\n", &error) &&
              !Graphics::parse("Sharpening=max\n", &error) && !Graphics::parse("AntiAliasing=msaa\n", &error) &&
              !Graphics::parse("Stats=all\n", &error),
          "unknown values are refused");
    Graphics::set(parsed);
    const std::string text = Graphics::serialize();
    Graphics::resetForTesting();
    check(Graphics::parse(text, &error), "serialize parses");
    const Graphics::Settings again = Graphics::current();
    check(again.resolution == 1080 && again.upscaler == Graphics::Upscaler::Bicubic && again.sharpening == Graphics::Sharpening::Medium &&
              again.fxaa && again.stats == Graphics::Stats::Detailed,
          "serialize round-trips");
}

void testFile() {
    Graphics::resetForTesting();
    unsetenv("PETARI_GRAPHICS");
    char pattern[] = "/tmp/petari-graphics-XXXXXX";
    const char* dir = mkdtemp(pattern);
    check(dir != nullptr, "temporary directory");
    const std::filesystem::path file = std::filesystem::path(dir) / "graphics.txt";
    std::string error;
    Graphics::set(settings(1440));
    check(Graphics::save(&error) && !std::filesystem::exists(file), "save before load writes nothing");
    check(Graphics::load(file, &error) && Graphics::current().resolution == 1440, "a missing file keeps the settings");
    Graphics::set(Graphics::Settings{});
    check(Graphics::save(&error) && read(file).find("Resolution=display\n") != std::string::npos, "Display is written as display");
    Graphics::set(settings(720, true));
    check(Graphics::save(&error) && read(file).find("Resolution=720\n") != std::string::npos &&
              read(file).find("AntiAliasing=fxaa\n") != std::string::npos,
          "save writes the settings");
    Graphics::set(Graphics::Settings{});
    check(Graphics::load(file, &error) && Graphics::current().resolution == 720 && Graphics::current().fxaa, "load reads them back");
    setenv("PETARI_GRAPHICS", "Resolution=2160,Stats=fps", 1);
    check(Graphics::load(file, &error) && Graphics::current().resolution == 2160 && Graphics::current().stats == Graphics::Stats::Fps &&
              Graphics::current().fxaa,
          "PETARI_GRAPHICS overrides single keys of the file");
    setenv("PETARI_GRAPHICS", "Resolution=1", 1);
    check(!Graphics::load(file, &error) && error.find("PETARI_GRAPHICS") == 0, "a bad PETARI_GRAPHICS is reported");
    unsetenv("PETARI_GRAPHICS");
    std::ofstream(file) << "Upscaler=x\n";
    check(!Graphics::load(file, &error) && error.find(file.string()) == 0, "a damaged file is reported with its path");
    std::filesystem::remove_all(dir);
}

void testOutputSize() {
    Graphics::resetForTesting();
    int width = -1, height = -1;
    Graphics::outputSize(&width, &height);
    check(width == 0 && height == 0, "no output size before the first frame");
    Graphics::setOutputSize(2560, 1440);
    Graphics::outputSize(&width, &height);
    check(width == 2560 && height == 1440, "the output size is kept");
}

void testFrameRateStatus() {
    Graphics::resetForTesting();
    Graphics::FrameRateStatus status = Graphics::frameRateStatus();
    check(status.displayHz == 0 && status.interpolatedPercent == -1 && status.latePercent == 0, "no frame rate status before the seam");
    Graphics::FrameRateStatus set;
    set.displayHz = 120;
    set.interpolatedPercent = 92;
    set.latePercent = 8;
    Graphics::setFrameRateStatus(set);
    status = Graphics::frameRateStatus();
    check(status.displayHz == 120 && status.interpolatedPercent == 92 && status.latePercent == 8, "the frame rate status is kept");
}

}  // namespace

int main() {
    testChoices();
    testParse();
    testFile();
    testOutputSize();
    testFrameRateStatus();
    std::printf("native graphics tests passed (%d checks)\n", checks);
    return 0;
}

#include "petari/home_menu.hpp"
#include "petari/graphics.hpp"
#include "petari/launch_stage.hpp"
#include "petari/progress.hpp"
#include "petari/volume.hpp"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <mutex>

namespace PetariNative::HomeMenu {

namespace {

constexpr float kDimOpacity = 0.5f;

// Layout in KPAD space before the widescreen correction.
constexpr float kPanelHalfWidth = 0.5f;
constexpr float kPanelTop = -0.66f;
constexpr float kPanelBottomMargin = 0.06f;  // below the last item
constexpr float kItemHalfWidth = 0.44f;
constexpr float kItemTop = -0.3f;
constexpr float kItemHeight = 0.19f;
constexpr float kItemSpacing = 0.24f;

// The Controls page: a larger panel, the lines, and Back at the bottom.
constexpr float kControlsHalfWidth = 0.86f;
constexpr float kControlsTop = -0.92f;
constexpr float kControlsTitleY = -0.82f;
constexpr float kControlsMessageY = -0.73f;
constexpr float kControlsLinesTop = -0.66f;
constexpr float kControlsLinesBottom = 0.62f;
constexpr float kControlsLinesHalfWidth = 0.8f;
constexpr float kControlsBackTop = 0.68f;
constexpr float kControlsBackHeight = 0.15f;
constexpr float kControlsBackHalfWidth = 0.2f;

constexpr const char* kListLabels[] = {"Resume", "Controls", "Mods", "Graphics", "My Progress", "Volume", "Restart from Title", "Quit"};
constexpr int kListCount = 8;
constexpr int kListResume = 0;
constexpr int kListControls = 1;
constexpr int kListMods = 2;
constexpr int kListGraphics = 3;
constexpr int kListProgress = 4;
constexpr int kListVolume = 5;  // a slider, not a button; above the actions that leave the game
constexpr int kListRestart = 6;
constexpr int kListQuit = 7;
constexpr int kGraphicsValues = 8;  // the Graphics page's value items, then Back
constexpr int kConfirmAccept = 0;
constexpr int kConfirmCancel = 1;

float progress(float time, float length) {
    return std::clamp(time / length, 0.0f, 1.0f);
}

}  // namespace

void Menu::create(const Config& config) {
    mConfig = config;
    if (!(mConfig.frameDelta > 0.0f)) {
        mConfig.frameDelta = 1.0f;
    }
    if (!(mConfig.widescreenAdjustX > 0.0f)) {
        mConfig.widescreenAdjustX = 1.0f;
    }
    mCreated = true;
    mPhase = Phase::Closed;
    mResult = Selection::None;
}

void Menu::setWidescreen(bool widescreen) {
    mWidescreen = widescreen;
}

void Menu::open() {
    if (!mCreated) {
        return;
    }
    mPhase = Phase::Opening;
    mResult = Selection::None;
    mConfirming = Selection::None;
    mLevelPending = false;
    mFocus = kListResume;
    mTime = 0.0f;
    mBlackStart = 0.0f;
    mPanelStart = 0.0f;
    mRepeatDir = 0;
    mRepeatTime = 0.0f;
    mPointerWasValid = false;
    mVolumeDrag = false;
    mSideDir = 0;
    mSideTime = 0.0f;
    play(Sound::HomeButton);
}

void Menu::update(const FrameInput& input) {
    const float dt = mConfig.frameDelta;
    const bool pointerMoved = input.pointerValid &&
                              (!mPointerWasValid || std::fabs(input.pointerX - mPointerX) > 1e-4f ||
                               std::fabs(input.pointerY - mPointerY) > 1e-4f);
    mPointerWasValid = input.pointerValid;
    if (input.pointerValid) {
        mPointerX = input.pointerX;
        mPointerY = input.pointerY;
    }

    switch (mPhase) {
    case Phase::Closed:
    case Phase::Finished:
        return;
    case Phase::Opening:
        mTime += dt;
        if (mTime >= kFadeFrames) {
            mPhase = Phase::List;
            mTime = 0.0f;
        }
        return;
    case Phase::Closing:
        mTime += dt;
        if (mTime >= kFadeFrames) {
            finish();
        }
        return;
    case Phase::BlackOut:
        mTime += dt;
        if (mTime >= kBlackOutFrames) {
            finish();
        }
        return;
    case Phase::List:
    case Phase::Confirm:
    case Phase::Controls:
    case Phase::Mods:
    case Phase::Levels:
    case Phase::Camera:
    case Phase::ModFolder:
    case Phase::Progress:
    case Phase::Graphics:
    case Phase::Cheats:
        break;
    }

    const int hovered = input.pointerValid ? itemAt(input.pointerX, input.pointerY) : -1;

    if (input.trigger & Button::Home) {
        play(Sound::ReturnApp);
        close();
        return;
    }
    // Escape presses Plus and B together; Plus alone decides that it is a back.
    if (input.trigger & Button::Plus) {
        back();
        return;
    }
    // Dragging the Volume slider: it follows the pointer while the button that
    // clicked it (A or B, either mouse button when remapped) is held.
    if (mVolumeDrag) {
        if (mPhase == Phase::List && (input.hold & (Button::A | Button::B)) && input.pointerValid) {
            setVolumeFromPointer(input.pointerX);
            return;
        }
        mVolumeDrag = false;
    }
    if (input.trigger & Button::A) {
        activate(mFocus);
        mVolumeDrag = mPhase == Phase::List && mFocus == kListVolume && hovered == kListVolume;
        return;
    }
    if (input.trigger & Button::B) {
        if (hovered >= 0) {
            setFocus(hovered, false);
            activate(hovered);
            mVolumeDrag = mPhase == Phase::List && hovered == kListVolume;
        } else {
            back();
        }
        return;
    }

    if (pointerMoved && hovered >= 0) {
        setFocus(hovered, true);
    }

    if (mPhase == Phase::Camera && mFocus == 1) {
        const std::uint32_t side = input.trigger & (Button::Left | Button::Right);
        if (side == Button::Left || side == Button::Right) {
            changeCameraValue(mFocus, side == Button::Left ? -1 : 1);
            return;
        }
    }
    if (mPhase == Phase::Cheats && mFocus == 0) {
        const std::uint32_t side = input.trigger & (Button::Left | Button::Right);
        if (side == Button::Left || side == Button::Right) {
            changeCheatsValue(mFocus, side == Button::Left ? -1 : 1);
            return;
        }
    }
    if (mPhase == Phase::Graphics && mFocus < kGraphicsValues) {
        const std::uint32_t side = input.trigger & (Button::Left | Button::Right);
        if (side == Button::Left || side == Button::Right) {
            changeGraphicsValue(mFocus, side == Button::Left ? -1 : 1);
            return;
        }
    }
    if (updateVolumeKeys(input)) {
        return;
    }
    if (mPhase == Phase::Progress && mFocus == 0) {
        const std::uint32_t side = input.trigger & (Button::Left | Button::Right);
        if (side == Button::Left || side == Button::Right) {
            changeProgressGalaxy(side == Button::Left ? -1 : 1);
            return;
        }
    }
    if (mPhase == Phase::Levels && (mFocus == 0 || mFocus == 1)) {
        const std::uint32_t side = input.trigger & (Button::Left | Button::Right);
        if (side == Button::Left || side == Button::Right) {
            changeLevelValue(mFocus, side == Button::Left ? -1 : 1);
            return;
        }
    }

    std::uint32_t dir = input.hold & (Button::Up | Button::Down);
    if (dir == (Button::Up | Button::Down)) {
        dir = 0;
    }
    if (dir != 0 && (input.trigger & dir)) {
        mRepeatDir = dir;
        mRepeatTime = 0.0f;
        moveFocus(dir == Button::Up ? -1 : 1);
    } else if (dir != 0 && dir == mRepeatDir) {
        mRepeatTime += dt;
        while (mRepeatTime >= kRepeatDelayFrames) {
            moveFocus(dir == Button::Up ? -1 : 1);
            mRepeatTime -= kRepeatIntervalFrames;
        }
    } else {
        // Held since before the menu took it (or released): no repeat
        // without a fresh press.
        mRepeatDir = 0;
        mRepeatTime = 0.0f;
    }
}

void Menu::setControls(const ControlsEntry* entries, int count) {
    mControlCount = std::clamp(count, 0, kMaxControls);
    for (int i = 0; i < mControlCount; i++) {
        mControls[i] = entries[i];
        // Always terminated, even if the caller filled every byte.
        mControls[i].action[sizeof(mControls[i].action) - 1] = '\0';
        mControls[i].inputs[sizeof(mControls[i].inputs) - 1] = '\0';
        mControls[i].pad[sizeof(mControls[i].pad) - 1] = '\0';
    }
}

void Menu::setMods(const ModsEntry* entries, int count) {
    mModCount = std::clamp(count, 0, kMaxMods);
    for (int i = 0; i < mModCount; i++) {
        mMods[i] = entries[i];
        mMods[i].label[sizeof(mMods[i].label) - 1] = '\0';
    }
}

void Menu::setCamera(const CameraOptions& options) {
    mCamera = options;
    mCamera.speed = std::clamp(mCamera.speed, 1, 5);
    mCameraChanged = false;
    refreshCameraLabels();
}

bool Menu::takeCameraChange(CameraOptions* options) {
    if (!mCameraChanged) {
        return false;
    }
    mCameraChanged = false;
    *options = mCamera;
    return true;
}

void Menu::refreshCameraLabels() {
    std::snprintf(mCameraLabels[0], sizeof(mCameraLabels[0]), "Odyssey camera: %s", mCamera.on ? "On" : "Off");
    std::snprintf(mCameraLabels[1], sizeof(mCameraLabels[1]), "Speed: %d", mCamera.speed);
    std::snprintf(mCameraLabels[2], sizeof(mCameraLabels[2]), "Invert horizontal: %s", mCamera.invertX ? "On" : "Off");
    std::snprintf(mCameraLabels[3], sizeof(mCameraLabels[3]), "Invert vertical: %s", mCamera.invertY ? "On" : "Off");
    std::snprintf(mCameraLabels[4], sizeof(mCameraLabels[4]), "Photo mode (P): %s", mCamera.photo ? "On" : "Off");
}

void Menu::changeCameraValue(int item, int delta) {
    switch (item) {
    case 0: mCamera.on = !mCamera.on; break;
    case 1: mCamera.speed = (mCamera.speed - 1 + delta + 5) % 5 + 1; break;
    case 2: mCamera.invertX = !mCamera.invertX; break;
    case 3: mCamera.invertY = !mCamera.invertY; break;
    case 4: mCamera.photo = !mCamera.photo; break;
    default: return;
    }
    mCameraChanged = true;
    refreshCameraLabels();
    play(item == 1 ? Sound::Focus : Sound::Select);
}

void Menu::setCheats(const CheatOptions& options) {
    mCheats = options;
    if (mCheats.lives >= 0) {
        mCheats.lives = std::clamp(mCheats.lives, kMinCheatLives, kMaxCheatLives);
    }
    mCheatsPage = true;
    mCheatsChanged = false;
    refreshCheatsLabels();
}

bool Menu::takeCheatsChange(CheatOptions* options) {
    if (!mCheatsChanged) {
        return false;
    }
    mCheatsChanged = false;
    *options = mCheats;
    return true;
}

void Menu::refreshCheatsLabels() {
    if (mCheats.lives >= 0) {
        std::snprintf(mCheatsLabels[0], sizeof(mCheatsLabels[0]), "1-Ups: %d", mCheats.lives);
    } else {
        std::snprintf(mCheatsLabels[0], sizeof(mCheatsLabels[0]), "1-Ups: in a galaxy only");
    }
    std::snprintf(mCheatsLabels[1], sizeof(mCheatsLabels[1]), "Keep 1-Ups when loading: %s", mCheats.keepLives ? "On" : "Off");
}

void Menu::changeCheatsValue(int item, int delta) {
    switch (item) {
    case 0:
        if (mCheats.lives < 0) {
            play(Sound::Cancel);  // no file in play: nothing to change
            return;
        }
        // Wraps 99 -> 1 and 1 -> 99, so any count is a few presses away.
        mCheats.lives = (mCheats.lives - kMinCheatLives + delta + kMaxCheatLives) % kMaxCheatLives + kMinCheatLives;
        break;
    case 1: mCheats.keepLives = !mCheats.keepLives; break;
    default: return;
    }
    mCheatsChanged = true;
    refreshCheatsLabels();
    play(item == 0 ? Sound::Focus : Sound::Select);
}

void Menu::setGraphics(const GraphicsOptions& options) {
    mGraphics = options;
    mGraphics.frameRate = mGraphics.frameRate >= 120 ? 120 : 60;
    mGraphics.vsync = std::clamp(mGraphics.vsync, 0, static_cast<int>(Graphics::VSync::Count) - 1);
    mGraphics.inputLatency = std::clamp(mGraphics.inputLatency, 0, static_cast<int>(Graphics::InputLatency::Count) - 1);
    mGraphics.resolution = Graphics::nearestResolution(mGraphics.resolution);
    mGraphics.upscaler = std::clamp(mGraphics.upscaler, 0, static_cast<int>(Graphics::Upscaler::Count) - 1);
    mGraphics.sharpening = std::clamp(mGraphics.sharpening, 0, static_cast<int>(Graphics::Sharpening::Count) - 1);
    mGraphics.stats = std::clamp(mGraphics.stats, 0, static_cast<int>(Graphics::Stats::Count) - 1);
    mGraphicsChanged = false;
    refreshGraphicsLabels();
}

bool Menu::takeGraphicsChange(GraphicsOptions* options) {
    if (!mGraphicsChanged) {
        return false;
    }
    mGraphicsChanged = false;
    *options = mGraphics;
    return true;
}

void Menu::setGraphicsOutput(int width, int height) {
    if (width == mOutputWidth && height == mOutputHeight) {
        return;
    }
    mOutputWidth = width;
    mOutputHeight = height;
    refreshGraphicsLabels();
}

void Menu::setGraphicsDisplayHz(int hz) {
    if (hz == mDisplayHz) {
        return;
    }
    mDisplayHz = hz;
    refreshGraphicsLabels();
}

void Menu::setGraphicsVariableRefresh(bool active) {
    if (active == mVariableRefresh) {
        return;
    }
    mVariableRefresh = active;
    refreshGraphicsLabels();
}

// Whether the chosen resolution is upscaled to the displayed image (unknown size: assumed).
bool Menu::graphicsUpscales() const {
    if (mGraphics.resolution == Graphics::kDisplay) {
        return false;
    }
    return mOutputHeight <= 0 || mGraphics.resolution < mOutputHeight;
}

void Menu::refreshGraphicsLabels() {
    const int resolution = mGraphics.resolution;
    if (mGraphics.frameRate < 120) {
        std::snprintf(mGraphicsLabels[0], sizeof(mGraphicsLabels[0]), "Frame rate: 60");
    } else if (mDisplayHz > 0 && mDisplayHz < 100) {
        std::snprintf(mGraphicsLabels[0], sizeof(mGraphicsLabels[0]), "Frame rate: 120 (%d Hz display)", mDisplayHz);
    } else {
        std::snprintf(mGraphicsLabels[0], sizeof(mGraphicsLabels[0]), "Frame rate: 120 (interpolated)");
    }
    std::snprintf(mGraphicsLabels[1], sizeof(mGraphicsLabels[1]), "V-Sync: %s",
                  Graphics::vsyncName(static_cast<Graphics::VSync>(mGraphics.vsync)));
    std::snprintf(mGraphicsLabels[2], sizeof(mGraphicsLabels[2]), "Input latency: %s",
                  Graphics::inputLatencyName(static_cast<Graphics::InputLatency>(mGraphics.inputLatency)));
    std::snprintf(mGraphicsLabels[3], sizeof(mGraphicsLabels[3]), "Resolution: %s", Graphics::resolutionName(resolution));
    if (graphicsUpscales()) {
        std::snprintf(mGraphicsLabels[4], sizeof(mGraphicsLabels[4]), "Upscaler: %s",
                      Graphics::upscalerName(static_cast<Graphics::Upscaler>(mGraphics.upscaler)));
    } else if (resolution == Graphics::kDisplay || resolution == mOutputHeight) {
        std::snprintf(mGraphicsLabels[4], sizeof(mGraphicsLabels[4]), "Upscaler: not needed at 1:1");
    } else {
        std::snprintf(mGraphicsLabels[4], sizeof(mGraphicsLabels[4]), "Downscaler: Area (automatic)");
    }
    std::snprintf(mGraphicsLabels[5], sizeof(mGraphicsLabels[5]), "Sharpening: %s",
                  Graphics::sharpeningName(static_cast<Graphics::Sharpening>(mGraphics.sharpening)));
    std::snprintf(mGraphicsLabels[6], sizeof(mGraphicsLabels[6]), "Anti-aliasing: %s", mGraphics.fxaa ? "FXAA" : "Off");
    std::snprintf(mGraphicsLabels[7], sizeof(mGraphicsLabels[7]), "Stats: %s",
                  Graphics::statsName(static_cast<Graphics::Stats>(mGraphics.stats)));
    if (mGraphics.frameRate >= 120 && mDisplayHz > 0 && mDisplayHz < 100) {
        std::snprintf(mGraphicsMessage, sizeof(mGraphicsMessage),
                      "120 frames per second need a display at 100 Hz or more; this one shows %d Hz.", mDisplayHz);
    } else if (mGraphics.vsync == static_cast<int>(Graphics::VSync::Variable) && !mVariableRefresh) {
        std::snprintf(mGraphicsMessage, sizeof(mGraphicsMessage),
                      "Variable needs a ProMotion or Adaptive-Sync display in fullscreen; here it works as On.");
    } else if (mOutputWidth > 0 && mOutputHeight > 0) {
        int width = 0, height = 0;
        Graphics::renderSize(resolution, mOutputWidth, mOutputHeight, &width, &height);
        std::snprintf(mGraphicsMessage, sizeof(mGraphicsMessage), "Renders %d x %d, shown at %d x %d (%s)", width, height, mOutputWidth,
                      mOutputHeight, height < mOutputHeight ? "upscaled" : height > mOutputHeight ? "supersampled" : "1:1");
    } else {
        std::snprintf(mGraphicsMessage, sizeof(mGraphicsMessage), "Left/Right changes a value. Saved in graphics.txt.");
    }
}

void Menu::changeGraphicsValue(int item, int delta) {
    const auto cycle = [delta](int value, int count) { return (value + delta % count + count) % count; };
    switch (item) {
    case 0: mGraphics.frameRate = mGraphics.frameRate >= 120 ? 60 : 120; break;
    case 1: mGraphics.vsync = cycle(mGraphics.vsync, static_cast<int>(Graphics::VSync::Count)); break;
    case 2: mGraphics.inputLatency = cycle(mGraphics.inputLatency, static_cast<int>(Graphics::InputLatency::Count)); break;
    case 3: {
        int index = 0;
        while (index < Graphics::kResolutionCount - 1 && Graphics::kResolutions[index] != mGraphics.resolution) index++;
        mGraphics.resolution = Graphics::kResolutions[cycle(index, Graphics::kResolutionCount)];
        break;
    }
    case 4:
        if (!graphicsUpscales()) {
            return;  // no choice: 1:1, or the area filter when supersampling
        }
        mGraphics.upscaler = cycle(mGraphics.upscaler, static_cast<int>(Graphics::Upscaler::Count));
        break;
    case 5: mGraphics.sharpening = cycle(mGraphics.sharpening, static_cast<int>(Graphics::Sharpening::Count)); break;
    case 6: mGraphics.fxaa = !mGraphics.fxaa; break;
    case 7: mGraphics.stats = cycle(mGraphics.stats, static_cast<int>(Graphics::Stats::Count)); break;
    default: return;
    }
    mGraphicsChanged = true;
    refreshGraphicsLabels();
    play(item == 0 || item == 2 || item == 6 ? Sound::Select : Sound::Focus);
}

void Menu::setVolume(int percent) {
    mVolume = Volume::snap(percent);
    mVolumeChanged = false;
}

bool Menu::takeVolumeChange(int* percent) {
    if (!mVolumeChanged) {
        return false;
    }
    mVolumeChanged = false;
    *percent = mVolume;
    return true;
}

void Menu::changeVolume(int percent) {
    percent = Volume::snap(percent);
    if (percent == mVolume) {
        return;
    }
    mVolume = percent;
    mVolumeChanged = true;
    play(Sound::Focus);  // one tick per step, at the new volume
}

void Menu::setVolumeFromPointer(float x) {
    const Rect track = sliderTrack(itemRect(kListVolume));
    const float t = std::clamp((x - track.x0) / (track.x1 - track.x0), 0.0f, 1.0f);
    changeVolume(static_cast<int>(std::lround(t * 100.0f)));
}

bool Menu::updateVolumeKeys(const FrameInput& input) {
    std::uint32_t side = input.hold & (Button::Left | Button::Right);
    if (mPhase != Phase::List || mFocus != kListVolume || side == (Button::Left | Button::Right)) {
        side = 0;
    }
    if (side == 0 || (side != mSideDir && !(input.trigger & side))) {
        // Released, or held since before the slider had the focus: no repeat without a fresh press.
        mSideDir = 0;
        mSideTime = 0.0f;
        return false;
    }
    const int step = side == Button::Left ? -Volume::kStep : Volume::kStep;
    if (input.trigger & side) {
        mSideDir = side;
        mSideTime = 0.0f;
        changeVolume(mVolume + step);
        return true;
    }
    mSideTime += mConfig.frameDelta;
    while (mSideTime >= kRepeatDelayFrames) {
        changeVolume(mVolume + step);
        mSideTime -= kRepeatIntervalFrames;
    }
    return false;
}

void Menu::setFolderMods(const FolderModEntry* entries, int count) {
    mFolderPage = true;
    mFolderCount = std::clamp(count, 0, kMaxFolderMods);
    for (int i = 0; i < mFolderCount; i++) {
        mFolderMods[i] = entries[i];
        mFolderMods[i].label[sizeof(mFolderMods[i].label) - 1] = '\0';
    }
    mFolderPageIndex = std::min(mFolderPageIndex, std::max(0, folderPages() - 1));
}

std::uint64_t Menu::takeFolderToggles() {
    const std::uint64_t toggles = mFolderToggles;
    mFolderToggles = 0;
    return toggles;
}

void Menu::refreshFolderLabels() {
    for (int i = 0; i < folderShown(); i++) {
        const FolderModEntry& mod = mFolderMods[mFolderPageIndex * kFolderPageSize + i];
        std::snprintf(mFolderLabels[i], sizeof(mFolderLabels[i]), "%s: %s", mod.label, mod.on ? "On" : "Off");
    }
    if (mFolderCount == 0) {
        std::snprintf(mFolderMessage, sizeof(mFolderMessage), "No mods found. Put mod folders in mods/ in the user folder.");
    } else {
        std::snprintf(mFolderMessage, sizeof(mFolderMessage), "Replace disc files. Page %d of %d. Applies after restarting the game.",
                      mFolderPageIndex + 1, std::max(1, folderPages()));
    }
}

namespace {
const char* missionKind(const App::LaunchStage::Galaxy& galaxy, int mission) {
    const char digit = static_cast<char>('0' + mission);
    if (std::strchr(galaxy.comets, digit) != nullptr) return " (comet)";
    if (std::strchr(galaxy.hidden, digit) != nullptr) return " (hidden star)";
    return "";
}

void formatTime(double seconds, char* out, size_t size) {
    const int whole = static_cast<int>(seconds);
    std::snprintf(out, size, "%d:%02d.%02d", whole / 60, whole % 60, static_cast<int>((seconds - whole) * 100.0 + 0.5) % 100);
}
}  // namespace

void Menu::refreshProgress() {
    int count = 0;
    const App::LaunchStage::Galaxy* galaxies = App::LaunchStage::galaxies(&count);
    mProgressGalaxy = count > 0 ? std::clamp(mProgressGalaxy, 0, count - 1) : 0;
    mProgressLineCount = 0;
    if (count == 0) {
        std::snprintf(mProgressLabels[0], sizeof(mProgressLabels[0]), "No galaxies");
        return;
    }
    const App::LaunchStage::Galaxy& galaxy = galaxies[mProgressGalaxy];
    int clearedHere = 0;
    ControlsEntry& header = mProgressLines[mProgressLineCount++];
    std::memset(&header, 0, sizeof(header));
    std::snprintf(header.inputs, sizeof(header.inputs), "Best time / deaths / coins / Star Bits");
    std::snprintf(header.pad, sizeof(header.pad), "Clears, first clear");
    for (int mission = 1; mission <= galaxy.missions && mProgressLineCount < 8; mission++) {
        ControlsEntry& line = mProgressLines[mProgressLineCount++];
        std::memset(&line, 0, sizeof(line));
        std::snprintf(line.action, sizeof(line.action), "Mission %d%s", mission, missionKind(galaxy, mission));
        Progress::Mission record;
        if (Progress::find(galaxy.stage, mission, &record)) {
            clearedHere++;
            char time[24];
            formatTime(record.bestTimeS, time, sizeof(time));
            std::snprintf(line.inputs, sizeof(line.inputs), "Cleared %s  %d  %d  %d", time, record.fewestDeaths, record.bestCoins,
                          record.bestStarBits);
            std::snprintf(line.pad, sizeof(line.pad), "x%d  %.10s", record.clears, record.firstClear.c_str());
        } else {
            std::snprintf(line.inputs, sizeof(line.inputs), "Not cleared yet");
        }
    }
    std::snprintf(mProgressLabels[0], sizeof(mProgressLabels[0]), "<  %s  >", galaxy.name);
    std::snprintf(mProgressLabels[1], sizeof(mProgressLabels[1]), mProgressResetArmed ? "Press A again to erase everything" : "Reset progress...");
    std::snprintf(mProgressLabels[2], sizeof(mProgressLabels[2]), "Badges: %s", Progress::badgesEnabled() ? "On" : "Off");
    std::snprintf(mProgressLabels[3], sizeof(mProgressLabels[3]), "Back");
    std::snprintf(mProgressMessage, sizeof(mProgressMessage), "%s: %d of %d cleared here, %d in all. Your save is not changed.",
                  App::LaunchStage::domeName(galaxy.dome), clearedHere, galaxy.missions, Progress::clearedCount());
}

void Menu::changeProgressGalaxy(int delta) {
    int count = 0;
    App::LaunchStage::galaxies(&count);
    if (count > 0) {
        mProgressGalaxy = (mProgressGalaxy + delta + count) % count;
    }
    mProgressResetArmed = false;
    refreshProgress();
    play(Sound::Focus);
}

bool Menu::takeLevelRequest(const char** stage, int* mission) {
    if (!mLevelPending || mPhase != Phase::Finished) {
        return false;
    }
    mLevelPending = false;
    int count = 0;
    const App::LaunchStage::Galaxy* galaxies = App::LaunchStage::galaxies(&count);
    *stage = galaxies[mLevelGalaxy].stage;
    *mission = mLevelMission;
    return true;
}

void Menu::refreshLevelLabels() {
    int count = 0;
    const App::LaunchStage::Galaxy& galaxy = App::LaunchStage::galaxies(&count)[mLevelGalaxy];
    const char digit = static_cast<char>('0' + mLevelMission);
    const bool comet = std::strchr(galaxy.comets, digit) != nullptr;
    const bool hidden = std::strchr(galaxy.hidden, digit) != nullptr;
    std::snprintf(mLevelLabels[0], sizeof(mLevelLabels[0]), "%s", galaxy.name);
    std::snprintf(mLevelLabels[1], sizeof(mLevelLabels[1]), "Mission %d of %d%s", mLevelMission, galaxy.missions,
                  comet ? " (comet)" : hidden ? " (hidden star)" : "");
    std::snprintf(mLevelMessage, sizeof(mLevelMessage), "%s. Left/Right changes; your save is not changed.",
                  App::LaunchStage::domeName(galaxy.dome));
}

void Menu::changeLevelValue(int item, int delta) {
    int count = 0;
    const App::LaunchStage::Galaxy* galaxies = App::LaunchStage::galaxies(&count);
    if (item == 0) {
        mLevelGalaxy = (mLevelGalaxy + delta + count) % count;
        mLevelMission = 1;
    } else {
        const int missions = galaxies[mLevelGalaxy].missions;
        mLevelMission = (mLevelMission - 1 + delta + missions) % missions + 1;
    }
    refreshLevelLabels();
    play(Sound::Focus);
}

std::uint32_t Menu::takeModToggles() {
    const std::uint32_t toggles = mModToggles;
    mModToggles = 0;
    return toggles;
}

void Menu::startBlackOut() {
    switch (mPhase) {
    case Phase::Opening:
    case Phase::List:
    case Phase::Confirm:
    case Phase::Controls:
    case Phase::Mods:
    case Phase::Levels:
    case Phase::Camera:
    case Phase::ModFolder:
    case Phase::Progress:
    case Phase::Graphics:
    case Phase::Cheats:
    case Phase::Closing:
        blackOut(Selection::Restart);
        break;
    case Phase::BlackOut:
        // Already fading after Restart or Quit: the console reset takes over,
        // and HomeButtonLayout expects the reset result.
        mResult = Selection::Restart;
        break;
    case Phase::Closed:
    case Phase::Finished:
        break;
    }
}

View Menu::view() const {
    View view;
    view.phase = mPhase;
    switch (mPhase) {
    case Phase::Closed:
    case Phase::Finished:
        return view;
    case Phase::Opening:
        view.panelOpacity = progress(mTime, kFadeFrames);
        break;
    case Phase::List:
    case Phase::Confirm:
    case Phase::Controls:
    case Phase::Mods:
    case Phase::Levels:
    case Phase::Camera:
    case Phase::ModFolder:
    case Phase::Progress:
    case Phase::Graphics:
    case Phase::Cheats:
        view.panelOpacity = 1.0f;
        break;
    case Phase::Closing:
        view.panelOpacity = mPanelStart * (1.0f - progress(mTime, kFadeFrames));
        break;
    case Phase::BlackOut:
        view.panelOpacity = mPanelStart;
        view.blackOpacity = mBlackStart + (1.0f - mBlackStart) * progress(mTime, kBlackOutFrames);
        break;
    }
    view.visible = true;
    view.dimOpacity = kDimOpacity * view.panelOpacity;

    const float ax = adjustX();

    const bool confirm = mConfirming != Selection::None;
    const bool controls = mPhase == Phase::Controls;
    const bool progressPage = mPhase == Phase::Progress;
    if (controls) {
        view.title = "Controls";
        view.message = "Change them in controls.txt in the game's user folder.";
        view.items[0].label = "Back";
        view.lineCount = mControlCount;
        for (int i = 0; i < mControlCount; i++) {
            view.lines[i] = mControls[i];
        }
        view.linesArea = {-kControlsLinesHalfWidth / ax, kControlsLinesTop, kControlsLinesHalfWidth / ax,
                          kControlsLinesBottom};
    } else if (mPhase == Phase::Progress) {
        view.title = "My Progress";
        view.message = mProgressMessage;
        for (int i = 0; i < 4; i++) {
            view.items[i].label = mProgressLabels[i];
        }
        view.lineCount = mProgressLineCount;
        for (int i = 0; i < mProgressLineCount; i++) {
            view.lines[i] = mProgressLines[i];
        }
        view.linesArea = {-kControlsLinesHalfWidth / ax, kControlsLinesTop + 0.2f, kControlsLinesHalfWidth / ax, 0.42f};
    } else if (mPhase == Phase::Mods) {
        view.title = "Mods";
        view.message = "Off by default. Saved in mods.txt; keys in controls.txt.";
        for (int i = 0; i < mModCount; i++) {
            view.items[i].label = mModLabels[i];
        }
        view.items[mModCount].label = "Odyssey camera...";
        view.items[mModCount + 1].label = "Level Select";
        if (mFolderPage) {
            view.items[mModCount + 2].label = "Mod folder...";
        }
        if (mCheatsPage) {
            view.items[modsCheatsIndex()].label = "Cheats...";
        }
        view.items[modsBackIndex()].label = "Back";
    } else if (mPhase == Phase::ModFolder) {
        view.title = "Mod folder";
        view.message = mFolderMessage;
        const int shown = folderShown();
        for (int i = 0; i < shown; i++) {
            view.items[i].label = mFolderLabels[i];
        }
        if (folderPages() > 1) {
            view.items[shown].label = "Next page";
        }
        view.items[shown + (folderPages() > 1 ? 1 : 0)].label = "Back";
    } else if (mPhase == Phase::Graphics) {
        view.title = "Graphics";
        view.message = mGraphicsMessage;
        for (int i = 0; i < kGraphicsValues; i++) {
            view.items[i].label = mGraphicsLabels[i];
        }
        view.items[kGraphicsValues].label = "Back";
    } else if (mPhase == Phase::Cheats) {
        view.title = "Cheats";
        view.message = "Left/Right: 1-Ups. They go into your save when the game saves.";
        view.items[0].label = mCheatsLabels[0];
        view.items[1].label = mCheatsLabels[1];
        view.items[2].label = "Back";
    } else if (mPhase == Phase::Camera) {
        view.title = "Odyssey camera";
        view.message = "Right stick or middle-drag orbits; wheel or Z/X zooms; C recentres. P: photo mode.";
        for (int i = 0; i < 5; i++) {
            view.items[i].label = mCameraLabels[i];
        }
        view.items[5].label = "Back";
    } else if (mPhase == Phase::Levels) {
        view.title = "Level Select";
        view.message = mLevelMessage;
        view.items[0].label = mLevelLabels[0];
        view.items[1].label = mLevelLabels[1];
        view.items[2].label = "Go";
        view.items[3].label = "Back";
    } else if (!confirm) {
        view.title = "Super Mario Galaxy";
        view.message = "Paused";
        for (int i = 0; i < kListCount; i++) {
            view.items[i].label = kListLabels[i];
        }
        view.items[kListVolume].slider = static_cast<float>(mVolume) / 100.0f;
    } else {
        const bool restart = mConfirming == Selection::Restart;
        view.title = restart ? "Restart from the title screen?" : "Quit Super Mario Galaxy?";
        view.message = "Progress since your last save will be lost.";
        view.items[kConfirmAccept].label = restart ? "Restart" : "Quit";
        view.items[kConfirmCancel].label = "Cancel";
    }
    view.itemCount = itemCount();
    if (controls || progressPage) {
        view.panel = {-kControlsHalfWidth / ax, kControlsTop, kControlsHalfWidth / ax,
                      itemRect(progressPage ? 3 : 0).y1 + kPanelBottomMargin};
        view.titleY = kControlsTitleY;
        view.messageY = kControlsMessageY;
    } else {
        view.panel = {-kPanelHalfWidth / ax, kPanelTop, kPanelHalfWidth / ax,
                      itemRect(view.itemCount - 1).y1 + kPanelBottomMargin};
        const float firstItemTop = itemRect(0).y0;
        view.titleY = kPanelTop + (firstItemTop - kPanelTop) * 0.33f;
        view.messageY = kPanelTop + (firstItemTop - kPanelTop) * 0.66f;
    }
    for (int i = 0; i < view.itemCount; i++) {
        view.items[i].rect = itemRect(i);
        view.items[i].focused = i == mFocus;
    }
    return view;
}

int Menu::itemCount() const {
    if (mPhase == Phase::Controls) {
        return 1;
    }
    if (mPhase == Phase::Mods) {
        return modsBackIndex() + 1;
    }
    if (mPhase == Phase::ModFolder) {
        return folderShown() + (folderPages() > 1 ? 1 : 0) + 1;
    }
    if (mPhase == Phase::Progress) {
        return 4;
    }
    if (mPhase == Phase::Camera) {
        return 6;
    }
    if (mPhase == Phase::Cheats) {
        return 3;
    }
    if (mPhase == Phase::Graphics) {
        return kGraphicsValues + 1;
    }
    if (mPhase == Phase::Levels) {
        return 4;
    }
    return mConfirming != Selection::None ? 2 : kListCount;
}

Rect Menu::itemRect(int index) const {
    const float ax = adjustX();
    if (mPhase == Phase::Controls) {
        return {-kControlsBackHalfWidth / ax, kControlsBackTop, kControlsBackHalfWidth / ax,
                kControlsBackTop + kControlsBackHeight};
    }
    if (mPhase == Phase::Progress) {
        // The galaxy selector under the message; Reset, Badges and Back side by side at the bottom.
        if (index == 0) return {-0.5f / ax, -0.64f, 0.5f / ax, -0.50f};
        const float left = -0.78f + 0.54f * static_cast<float>(index - 1);
        return {left / ax, 0.52f, (left + 0.5f) / ax, 0.67f};
    }
    // Six or more items (the Mods page) use a tighter column so they fit.
    const bool compact = itemCount() > 5;
    const bool dense = itemCount() > 6;  // seven items: the list with Volume, the Mods page with a Mod folder entry
    const bool densest = itemCount() > 8;  // nine: the Mods page with five mods and a Mod folder entry
    const bool crowded = itemCount() > 9;  // ten: the same with a Cheats entry
    const bool packed = itemCount() > 10;  // eleven: six mods, a Mod folder and a Cheats entry
    const float spacing = packed ? 0.122f : crowded ? 0.135f : densest ? 0.15f : dense ? 0.17f : compact ? 0.2f : kItemSpacing;
    const float top = (packed ? -0.45f : crowded ? -0.44f : densest ? -0.42f : dense ? -0.4f : compact ? -0.32f : kItemTop) +
                      spacing * static_cast<float>(index);
    return {-kItemHalfWidth / ax, top, kItemHalfWidth / ax,
            top + (packed ? 0.105f : crowded ? 0.115f : densest ? 0.125f : dense ? 0.14f : compact ? 0.16f : kItemHeight)};
}

int Menu::itemAt(float x, float y) const {
    for (int i = 0; i < itemCount(); i++) {
        if (itemRect(i).contains(x, y)) {
            return i;
        }
    }
    return -1;
}

void Menu::play(int num) const {
    if (mConfig.sound != nullptr) {
        mConfig.sound(Sound::EventPlaySound, num);
    }
}

void Menu::event(int event) const {
    if (mConfig.sound != nullptr) {
        mConfig.sound(event, 0);
    }
}

void Menu::setFocus(int focus, bool withSound) {
    if (focus == mFocus) {
        return;
    }
    mFocus = focus;
    if (mPhase == Phase::Progress && mProgressResetArmed && focus != 1) {
        mProgressResetArmed = false;  // moving away disarms the erase
        refreshProgress();
    }
    if (withSound) {
        play(Sound::Focus);
    }
}

void Menu::moveFocus(int delta) {
    setFocus(std::clamp(mFocus + delta, 0, itemCount() - 1), true);
}

void Menu::activate(int index) {
    if (mPhase == Phase::List) {
        switch (index) {
        case kListResume:
            play(Sound::ReturnApp);
            close();
            break;
        case kListControls:
            play(Sound::Select);
            mPhase = Phase::Controls;
            mFocus = 0;
            mRepeatDir = 0;
            break;
        case kListGraphics:
            play(Sound::Select);
            refreshGraphicsLabels();
            mPhase = Phase::Graphics;
            mFocus = 0;
            mRepeatDir = 0;
            break;
        case kListProgress:
            play(Sound::Select);
            mProgressResetArmed = false;
            refreshProgress();
            mPhase = Phase::Progress;
            mFocus = 0;
            mRepeatDir = 0;
            break;
        case kListMods:
            play(Sound::Select);
            for (int i = 0; i < mModCount; i++) {
                std::snprintf(mModLabels[i], sizeof(mModLabels[i]), "%s: %s", mMods[i].label, mMods[i].on ? "On" : "Off");
            }
            mPhase = Phase::Mods;
            mFocus = 0;
            mRepeatDir = 0;
            break;
        case kListVolume:
            // A click sets the slider where it lands; A without the pointer on it steps up.
            if (mPointerWasValid && itemRect(kListVolume).contains(mPointerX, mPointerY)) {
                setVolumeFromPointer(mPointerX);
            } else {
                changeVolume(mVolume + Volume::kStep);
            }
            break;
        case kListRestart:
        case kListQuit:
            play(Sound::Select);
            mConfirming = index == kListRestart ? Selection::Restart : Selection::Quit;
            mPhase = Phase::Confirm;
            mFocus = kConfirmCancel;
            mRepeatDir = 0;
            break;
        }
    } else if (mPhase == Phase::Controls) {
        play(Sound::Cancel);
        mPhase = Phase::List;
        mFocus = kListControls;
        mRepeatDir = 0;
    } else if (mPhase == Phase::Levels) {
        if (index == 0 || index == 1) {
            changeLevelValue(index, 1);
        } else if (index == 2) {
            play(Sound::Select);
            mLevelPending = true;
            close();
        } else {
            play(Sound::Cancel);
            mPhase = Phase::Mods;
            mFocus = mModCount + 1;
            mRepeatDir = 0;
        }
    } else if (mPhase == Phase::Progress) {
        if (index == 0) {
            changeProgressGalaxy(1);
        } else if (index == 1) {
            if (!mProgressResetArmed) {
                play(Sound::Select);
                mProgressResetArmed = true;
            } else {
                play(Sound::Select);
                mProgressResetArmed = false;
                Progress::reset();
            }
            refreshProgress();
        } else if (index == 2) {
            play(Sound::Select);
            Progress::setBadgesEnabled(!Progress::badgesEnabled());
            refreshProgress();
        } else {
            play(Sound::Cancel);
            mProgressResetArmed = false;
            mPhase = Phase::List;
            mFocus = kListProgress;
            mRepeatDir = 0;
        }
    } else if (mPhase == Phase::ModFolder) {
        const int shown = folderShown();
        const bool paged = folderPages() > 1;
        if (index >= 0 && index < shown) {
            play(Sound::Select);
            const int entry = mFolderPageIndex * kFolderPageSize + index;
            mFolderMods[entry].on = !mFolderMods[entry].on;
            mFolderToggles |= std::uint64_t{1} << entry;
            refreshFolderLabels();
        } else if (paged && index == shown) {
            play(Sound::Select);
            mFolderPageIndex = (mFolderPageIndex + 1) % folderPages();
            refreshFolderLabels();
            mFocus = 0;
        } else {
            play(Sound::Cancel);
            mPhase = Phase::Mods;
            mFocus = mModCount + 2;
            mRepeatDir = 0;
        }
    } else if (mPhase == Phase::Graphics) {
        if (index >= 0 && index < kGraphicsValues) {
            changeGraphicsValue(index, 1);
        } else {
            play(Sound::Cancel);
            mPhase = Phase::List;
            mFocus = kListGraphics;
            mRepeatDir = 0;
        }
    } else if (mPhase == Phase::Cheats) {
        if (index == 0 || index == 1) {
            changeCheatsValue(index, 1);
        } else {
            play(Sound::Cancel);
            mPhase = Phase::Mods;
            mFocus = modsCheatsIndex();
            mRepeatDir = 0;
        }
    } else if (mPhase == Phase::Camera) {
        if (index >= 0 && index < 5) {
            changeCameraValue(index, 1);
        } else {
            play(Sound::Cancel);
            mPhase = Phase::Mods;
            mFocus = mModCount;
            mRepeatDir = 0;
        }
    } else if (mPhase == Phase::Mods) {
        if (index == mModCount) {
            play(Sound::Select);
            refreshCameraLabels();
            mPhase = Phase::Camera;
            mFocus = 0;
            mRepeatDir = 0;
        } else if (index == mModCount + 1) {
            play(Sound::Select);
            refreshLevelLabels();
            mPhase = Phase::Levels;
            mFocus = 0;
            mRepeatDir = 0;
        } else if (mFolderPage && index == mModCount + 2) {
            play(Sound::Select);
            mFolderPageIndex = 0;
            refreshFolderLabels();
            mPhase = Phase::ModFolder;
            mFocus = 0;
            mRepeatDir = 0;
        } else if (mCheatsPage && index == modsCheatsIndex()) {
            play(Sound::Select);
            refreshCheatsLabels();
            mPhase = Phase::Cheats;
            mFocus = 0;
            mRepeatDir = 0;
        } else if (index >= 0 && index < mModCount) {
            play(Sound::Select);
            mMods[index].on = !mMods[index].on;
            mModToggles |= 1u << index;
            std::snprintf(mModLabels[index], sizeof(mModLabels[index]), "%s: %s", mMods[index].label,
                          mMods[index].on ? "On" : "Off");
        } else {
            play(Sound::Cancel);
            mPhase = Phase::List;
            mFocus = kListMods;
            mRepeatDir = 0;
        }
    } else if (mPhase == Phase::Confirm) {
        if (index == kConfirmAccept) {
            play(mConfirming == Selection::Restart ? Sound::ResetApp : Sound::GotoMenu);
            blackOut(mConfirming);
        } else {
            play(Sound::Cancel);
            mFocus = mConfirming == Selection::Restart ? kListRestart : kListQuit;
            mConfirming = Selection::None;
            mPhase = Phase::List;
            mRepeatDir = 0;
        }
    }
}

void Menu::back() {
    if (mPhase == Phase::Confirm) {
        activate(kConfirmCancel);
    } else if (mPhase == Phase::Controls) {
        activate(0);
    } else if (mPhase == Phase::Mods) {
        activate(modsBackIndex());
    } else if (mPhase == Phase::ModFolder) {
        activate(itemCount() - 1);
    } else if (mPhase == Phase::Progress) {
        activate(3);
    } else if (mPhase == Phase::Levels) {
        activate(3);
    } else if (mPhase == Phase::Camera) {
        activate(5);
    } else if (mPhase == Phase::Cheats) {
        activate(2);
    } else if (mPhase == Phase::Graphics) {
        activate(kGraphicsValues);
    } else {
        play(Sound::ReturnApp);
        close();
    }
}

void Menu::close() {
    mPanelStart = view().panelOpacity;
    mPhase = Phase::Closing;
    mTime = 0.0f;
    mResult = Selection::Resume;
    event(Sound::EventBeginExitAnim);
}

void Menu::blackOut(Selection result) {
    const View current = view();
    mPanelStart = current.panelOpacity;
    mBlackStart = current.blackOpacity;
    mPhase = Phase::BlackOut;
    mTime = 0.0f;
    mResult = result;
    event(Sound::EventBeginBlackOut);
}

void Menu::finish() {
    mPhase = Phase::Finished;
    event(Sound::EventEndMenu);
}

// --- Game instance and published view ---

namespace {
std::mutex gViewMutex;
View gView;
}  // namespace

Menu& instance() {
    static Menu menu;
    return menu;
}

View publishedView() {
    std::lock_guard<std::mutex> lock(gViewMutex);
    return gView;
}

void publish(const View& view) {
    std::lock_guard<std::mutex> lock(gViewMutex);
    gView = view;
}

}  // namespace PetariNative::HomeMenu

#include "Game/Scene/GameScenePauseControl.hpp"
#include "Game/AudioLib/AudSystem.hpp"
#include "Game/AudioLib/AudWrap.hpp"
#include "Game/LiveActor/Nerve.hpp"
#include "Game/Scene/GameScene.hpp"
#include "Game/Screen/GamePauseSequence.hpp"
#include "Game/System/PauseButtonCheckerInGame.hpp"

namespace {
    NEW_NERVE(GameScenePauseControlNormal, GameScenePauseControl, Normal);
};  // namespace

#ifdef PETARI_NATIVE
#include "Game/Util/GamePadUtil.hpp"
#include "Game/Util/SceneUtil.hpp"
#include <algorithm>
#include <cstdio>
#include <petari/pause_log.h>

namespace {
    // A + or - press followed until it is released: if the pause menu did not open, one line
    // in pause-log.txt says how long it was held (PauseButtonCheckerInGame needs 12 frames in
    // a row) and what refused it meanwhile (pause_log.h).
    struct PauseWatch {
        bool active;
        bool plus;
        s32 frames;
        s32 run;
        s32 longest;
        s32 sceneFrames;
        const char* scene;
        s32 aFrames;
        s32 bFrames;
        s32 motionFrames;
    };
    PauseWatch sWatch;
    const s32 cWatchLimit = 120;

    void watchPausePress(GameScene* pScene, const Nerve* pPauseMenuNerve, bool opened) {
        const bool plusTrigger = MR::testCorePadTriggerPlus(WPAD_CHAN0);
        const bool minusTrigger = MR::testCorePadTriggerMinus(WPAD_CHAN0);
        if (opened) {
            sWatch.active = false;
            return;
        }
        if (!sWatch.active) {
            // A press in the pause menu closes it: not followed.
            if ((!plusTrigger && !minusTrigger) || (pPauseMenuNerve != nullptr && pScene->isNerve(pPauseMenuNerve))) {
                return;
            }
            sWatch = PauseWatch();
            sWatch.active = true;
            sWatch.plus = plusTrigger;
        }
        const bool held = sWatch.plus ? MR::testCorePadButtonPlus(WPAD_CHAN0) : MR::testCorePadButtonMinus(WPAD_CHAN0);
        sWatch.run = held ? sWatch.run + 1 : 0;
        sWatch.longest = std::max(sWatch.longest, sWatch.run);
        if (held) {
            if (const char* pWhy = pScene->pauseRefusal()) {
                ++sWatch.sceneFrames;
                sWatch.scene = pWhy;
            } else if (MR::isOperatingWPad(WPAD_CHAN0)) {
                // As MR::isOperatingWPad: A or B held, or the remote moving.
                if (MR::testCorePadButtonA(WPAD_CHAN0)) {
                    ++sWatch.aFrames;
                } else if (MR::testCorePadButtonB(WPAD_CHAN0)) {
                    ++sWatch.bFrames;
                } else {
                    ++sWatch.motionFrames;
                }
            }
        }
        if (++sWatch.frames < cWatchLimit && held) {
            return;
        }
        sWatch.active = false;
        char reasons[256] = "";
        size_t used = 0;
        auto add = [&](const char* what, s32 count) {
            if (count > 0 && used < sizeof(reasons)) {
                const int n = std::snprintf(reasons + used, sizeof(reasons) - used, "%s%s (%d frames)", used > 0 ? ", " : "", what,
                                            static_cast< int >(count));
                used += n > 0 ? static_cast< size_t >(n) : 0;
            }
        };
        add(sWatch.scene != nullptr ? sWatch.scene : "", sWatch.sceneFrames);
        add("A held (a key or mouse button bound to A)", sWatch.aFrames);
        add("B held (a key or mouse button bound to B)", sWatch.bFrames);
        add("the remote moving (a spin just before)", sWatch.motionFrames);
        char line[512];
        std::snprintf(line, sizeof(line), "%s pressed in %s, scenario %d: no pause. Held %d frames in a row (the game needs 12)%s%s",
                      sWatch.plus ? "Plus (Escape)" : "Minus", MR::getCurrentStageName(), static_cast< int >(MR::getCurrentScenarioNo()),
                      static_cast< int >(sWatch.longest), used > 0 ? "; refused while held: " : "", reasons);
        petari_host_pause_log(line);
    }
}  // namespace
#endif

GameScenePauseControl::GameScenePauseControl(GameScene* pScene) : NerveExecutor("GameSceneポーズ制御") {
    mScene = pScene;
    mPauseChecker = nullptr;
    mPauseMenuOff = false;
    mPauseMenuNerve = nullptr;
    initNerve(GET_NERVE_ANON(GameScenePauseControlNormal));
    mPauseChecker = new PauseButtonCheckerInGame();
}

void GameScenePauseControl::registerNervePauseMenu(const Nerve* pNerve) {
    mPauseMenuNerve = pNerve;
}

void GameScenePauseControl::requestPauseMenuOff() {
    mPauseMenuOff = true;
}

void GameScenePauseControl::exeNormal() {
#ifdef PETARI_NATIVE
    watchPausePress(mScene, mPauseMenuNerve, tryStartPauseMenu());
#else
    tryStartPauseMenu();
#endif

    if (mPauseMenuOff) {
        AudWrap::getSystem()->exitPauseMenu();
        mScene->setNerveAfterPauseMenu();
        mPauseMenuOff = false;
        mScene->mPauseSeq->deactivate();
    }
}

bool GameScenePauseControl::tryStartPauseMenu() {
    if (mScene->isPermitToPauseMenu()) {
        mPauseChecker->update();

        if (mPauseChecker->isPermitToMinusPause()) {
            mScene->mPauseSeq->startPause(GamePauseSequence::ActivePause);
            mScene->setNerve(mPauseMenuNerve);
            return true;
        }

        if (mPauseChecker->isPermitToPlusPause()) {
            mScene->mPauseSeq->startPause(GamePauseSequence::ActivePause);
            mScene->setNerve(mPauseMenuNerve);
            return true;
        }
    }

    return false;
}

GameScenePauseControl::~GameScenePauseControl() {
}

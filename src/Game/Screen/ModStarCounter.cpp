// The counter of the mods' stars (Game/Screen/ModStarCounter.hpp), as StarCounter.
#include "Game/Screen/ModStarCounter.hpp"
#include "Game/LiveActor/Nerve.hpp"
#include "Game/Screen/CountUpPaneRumbler.hpp"
#include "Game/Screen/CounterLayoutAppearer.hpp"
#include "Game/System/GameDataFunction.hpp"
#include "Game/Util/FileUtil.hpp"
#include "Game/Util/LayoutUtil.hpp"
#include "Game/Util/ObjUtil.hpp"
#include "Game/Util/SceneUtil.hpp"

namespace NrvModStarCounter {
    NEW_NERVE(ModStarCounterNrvAppear, ModStarCounter, Appear);
    NEW_NERVE(ModStarCounterNrvWait, ModStarCounter, Wait);
    NEW_NERVE(ModStarCounterNrvCountUp, ModStarCounter, CountUp);
    NEW_NERVE(ModStarCounterNrvDisappear, ModStarCounter, Disappear);
};  // namespace NrvModStarCounter

namespace {
    // One line below the star counter (layout units, y down).
    const TVec2f cOffset(0.0f, 44.0f);
}  // namespace

ModStarCounter::ModStarCounter()
    : LayoutActor("Modスターカウンタ", true), mPowerStarNum(0), mLayoutAppearer(nullptr), mPaneRumbler(nullptr) {
}

bool ModStarCounter::isExistLayout() {
    return MR::isFileExist("/LayoutData/GuglisStars.arc", false);
}

void ModStarCounter::init(const JMapInfoIter& rIter) {
    initLayoutManager("GuglisStars", 2);
    MR::createAndAddPaneCtrl(this, "Counter", 1);

    mLayoutAppearer = new CounterLayoutAppearer(this, TVec2f(-50.0f, 0.0f));
    mPaneRumbler = new CountUpPaneRumbler(this, "Counter");

    MR::connectToSceneLayout(this);
    initNerve(GET_NERVE(ModStarCounter, ModStarCounterNrvAppear));
}

void ModStarCounter::appear() {
    mLayoutAppearer->appear(cOffset);
    mPaneRumbler->reset();
    MR::startAnim(this, "Wait", 1);

    mPowerStarNum = GameDataFunction::getModPowerStarNum();

    MR::setTextBoxNumberRecursive(this, "Counter", mPowerStarNum);
    setNerve(GET_NERVE(ModStarCounter, ModStarCounterNrvAppear));
    LayoutActor::appear();
    MR::requestMovementOn(this);
}

void ModStarCounter::disappear() {
    MR::requestMovementOn(this);
    setNerve(GET_NERVE(ModStarCounter, ModStarCounterNrvDisappear));
}

bool ModStarCounter::isWait() const {
    return isNerve(GET_NERVE(ModStarCounter, ModStarCounterNrvWait));
}

void ModStarCounter::control() {
    mLayoutAppearer->update();
    mPaneRumbler->update();
}

void ModStarCounter::exeAppear() {
    if (mLayoutAppearer->isAppeared()) {
        setNerve(GET_NERVE(ModStarCounter, ModStarCounterNrvWait));
    }
}

void ModStarCounter::exeWait() {
    if (mPowerStarNum < GameDataFunction::getModPowerStarNum()) {
        setNerve(GET_NERVE(ModStarCounter, ModStarCounterNrvCountUp));
    }
}

void ModStarCounter::exeCountUp() {
    if (MR::isFirstStep(this)) {
        mPowerStarNum++;

        MR::setTextBoxNumberRecursive(this, "Counter", mPowerStarNum);
        MR::startAnim(this, "Flash", 0);
        mPaneRumbler->start();
    }

    if (MR::isAnimStopped(this, 0) && !mPaneRumbler->isRumbling()) {
        setNerve(GET_NERVE(ModStarCounter, ModStarCounterNrvWait));
    }
}

void ModStarCounter::exeDisappear() {
    if (MR::isFirstStep(this)) {
        mLayoutAppearer->disappear();
    }

    if (mLayoutAppearer->isDisappeared()) {
        kill();
    }
}

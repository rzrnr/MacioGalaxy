// The purple star counter (Game/Screen/PurpleStarCounter.hpp), as StarCounter.
#include "Game/Screen/PurpleStarCounter.hpp"
#include "Game/LiveActor/Nerve.hpp"
#include "Game/Screen/CountUpPaneRumbler.hpp"
#include "Game/Screen/CounterLayoutAppearer.hpp"
#include "Game/System/GameDataFunction.hpp"
#include "Game/Util/FileUtil.hpp"
#include "Game/Util/LayoutUtil.hpp"
#include "Game/Util/ObjUtil.hpp"
#include "Game/Util/SceneUtil.hpp"

namespace NrvPurpleStarCounter {
    NEW_NERVE(PurpleStarCounterNrvAppear, PurpleStarCounter, Appear);
    NEW_NERVE(PurpleStarCounterNrvWait, PurpleStarCounter, Wait);
    NEW_NERVE(PurpleStarCounterNrvCountUp, PurpleStarCounter, CountUp);
    NEW_NERVE(PurpleStarCounterNrvDisappear, PurpleStarCounter, Disappear);
};  // namespace NrvPurpleStarCounter

namespace {
    // One line below the star counter (layout units, y down).
    const TVec2f cOffset(0.0f, 44.0f);
}  // namespace

PurpleStarCounter::PurpleStarCounter()
    : LayoutActor("紫スターカウンタ", true), mPowerStarNum(0), mLayoutAppearer(nullptr), mPaneRumbler(nullptr) {
}

bool PurpleStarCounter::isExistLayout() {
    return MR::isFileExist("/LayoutData/PurpleStars.arc", false);
}

void PurpleStarCounter::init(const JMapInfoIter& rIter) {
    initLayoutManager("PurpleStars", 2);
    MR::createAndAddPaneCtrl(this, "Counter", 1);

    mLayoutAppearer = new CounterLayoutAppearer(this, TVec2f(-50.0f, 0.0f));
    mPaneRumbler = new CountUpPaneRumbler(this, "Counter");

    MR::connectToSceneLayout(this);
    initNerve(GET_NERVE(PurpleStarCounter, PurpleStarCounterNrvAppear));
}

void PurpleStarCounter::appear() {
    mLayoutAppearer->appear(cOffset);
    mPaneRumbler->reset();
    MR::startAnim(this, "Wait", 1);

    mPowerStarNum = GameDataFunction::getModPowerStarNum();

    MR::setTextBoxNumberRecursive(this, "Counter", mPowerStarNum);
    setNerve(GET_NERVE(PurpleStarCounter, PurpleStarCounterNrvAppear));
    LayoutActor::appear();
    MR::requestMovementOn(this);
}

void PurpleStarCounter::disappear() {
    MR::requestMovementOn(this);
    setNerve(GET_NERVE(PurpleStarCounter, PurpleStarCounterNrvDisappear));
}

bool PurpleStarCounter::isWait() const {
    return isNerve(GET_NERVE(PurpleStarCounter, PurpleStarCounterNrvWait));
}

void PurpleStarCounter::control() {
    mLayoutAppearer->update();
    mPaneRumbler->update();
}

void PurpleStarCounter::exeAppear() {
    if (mLayoutAppearer->isAppeared()) {
        setNerve(GET_NERVE(PurpleStarCounter, PurpleStarCounterNrvWait));
    }
}

void PurpleStarCounter::exeWait() {
    if (mPowerStarNum < GameDataFunction::getModPowerStarNum()) {
        setNerve(GET_NERVE(PurpleStarCounter, PurpleStarCounterNrvCountUp));
    }
}

void PurpleStarCounter::exeCountUp() {
    if (MR::isFirstStep(this)) {
        mPowerStarNum++;

        MR::setTextBoxNumberRecursive(this, "Counter", mPowerStarNum);
        MR::startAnim(this, "Flash", 0);
        mPaneRumbler->start();
    }

    if (MR::isAnimStopped(this, 0) && !mPaneRumbler->isRumbling()) {
        setNerve(GET_NERVE(PurpleStarCounter, PurpleStarCounterNrvWait));
    }
}

void PurpleStarCounter::exeDisappear() {
    if (MR::isFirstStep(this)) {
        mLayoutAppearer->disappear();
    }

    if (mLayoutAppearer->isDisappeared()) {
        kill();
    }
}

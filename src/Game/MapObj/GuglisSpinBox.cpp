// Example of a new object with its own logic (Game/MapObj/GuglisSpinBox.hpp, native/CUSTOM_GALAXY.md).
#include "Game/MapObj/GuglisSpinBox.hpp"
#include "Game/LiveActor/HitSensor.hpp"
#include "Game/LiveActor/Nerve.hpp"
#include "Game/Util.hpp"

#include <cmath>

namespace NrvGuglisSpinBox {
    NEW_NERVE(GuglisSpinBoxNrvWait, GuglisSpinBox, Wait);
    NEW_NERVE(GuglisSpinBoxNrvHit, GuglisSpinBox, Hit);
    NEW_NERVE(GuglisSpinBoxNrvBurst, GuglisSpinBox, Burst);
};  // namespace NrvGuglisSpinBox

namespace {
    constexpr s32 kDefaultHits = 5;
    constexpr s32 kBurstCoins = 8;
    constexpr s32 kHitSteps = 24;  // swell and cool-down after a hit
    constexpr f32 kBobHeight = 30.0f;
    constexpr f32 kTurnDegreesPerStep = 1.5f;
}  // namespace

GuglisSpinBox::GuglisSpinBox(const char* pName)
    : LiveActor(pName), mBasePos(0.0f, 0.0f, 0.0f), mBaseScale(1.0f, 1.0f, 1.0f), mHitsLeft(kDefaultHits), mTime(0) {
}

void GuglisSpinBox::init(const JMapInfoIter& rIter) {
    MR::initDefaultPos(this, rIter);
    initModelManagerWithAnm("PunchBox", nullptr, false);
    MR::connectToSceneMapObjStrongLight(this);
    initSound(4, false);

    s32 hits = kDefaultHits;
    if (rIter.isValid()) {
        MR::getJMapInfoArg0NoInit(rIter, &hits);
    }
    mHitsLeft = hits > 0 ? hits : kDefaultHits;

    initHitSensor(1);
    MR::addHitSensorMapObj(this, "body", 8, mScale.x * 110.0f, TVec3f(0.0f, mScale.x * 90.0f, 0.0f));
    MR::declareCoin(this, mHitsLeft - 1 + kBurstCoins);

    mBasePos.set(mPosition);
    mBaseScale.set(mScale);
    initNerve(GET_NERVE(GuglisSpinBox, GuglisSpinBoxNrvWait));
    MR::setClippingFar100m(this);
    makeActorAppeared();
}

// Floats: bobs along its up axis and turns about it, whatever it does.
void GuglisSpinBox::control() {
    mTime++;
    TVec3f up;
    MR::calcUpVec(&up, this);
    const f32 bob = kBobHeight * std::sin(static_cast< f32 >(mTime) * 0.05f);
    mPosition.set(mBasePos.x + up.x * bob, mBasePos.y + up.y * bob, mBasePos.z + up.z * bob);
    mRotation.y = static_cast< f32 >(std::fmod(mRotation.y + kTurnDegreesPerStep, 360.0f));
}

void GuglisSpinBox::exeWait() {
}

void GuglisSpinBox::exeHit() {
    if (MR::isFirstStep(this)) {
        MR::appearCoinPop(this, mPosition, 1);
        MR::startSound(this, "SE_OJ_STAR_PIECE_BURST");
    }
    // Swells to 1.4 times its size and settles back.
    const f32 swell = 1.0f + 0.4f * std::sin(static_cast< f32 >(getNerveStep()) * 3.14159f / kHitSteps);
    mScale.set(mBaseScale.x * swell, mBaseScale.y * swell, mBaseScale.z * swell);
    if (MR::isStep(this, kHitSteps)) {
        mScale.set(mBaseScale);
        setNerve(GET_NERVE(GuglisSpinBox, GuglisSpinBoxNrvWait));
    }
}

void GuglisSpinBox::exeBurst() {
    if (MR::isFirstStep(this)) {
        MR::startSound(this, "SE_OJ_PUNCH_BOX_BREAK");
    }
    // Shrinks away, then the coins fly out where it was.
    const f32 shrink = 1.0f - static_cast< f32 >(getNerveStep()) / 12.0f;
    mScale.set(mBaseScale.x * shrink, mBaseScale.y * shrink, mBaseScale.z * shrink);
    if (MR::isStep(this, 12)) {
        MR::appearCoinPop(this, mPosition, kBurstCoins);
        kill();
    }
}

bool GuglisSpinBox::hit() {
    if (!isNerve(GET_NERVE(GuglisSpinBox, GuglisSpinBoxNrvWait))) {
        return false;
    }
    if (--mHitsLeft <= 0) {
        getSensor("body")->invalidate();
        setNerve(GET_NERVE(GuglisSpinBox, GuglisSpinBoxNrvBurst));
    } else {
        setNerve(GET_NERVE(GuglisSpinBox, GuglisSpinBoxNrvHit));
    }
    return true;
}

bool GuglisSpinBox::receiveMsgPlayerAttack(u32 msg, HitSensor*, HitSensor*) {
    return (MR::isMsgPlayerSpinAttack(msg) || MR::isMsgPlayerHitAll(msg)) && hit();
}

bool GuglisSpinBox::receiveOtherMsg(u32 msg, HitSensor*, HitSensor*) {
    if (msg == ACTMES_TORNADO_ATTACK || msg == ACTMES_TORNADO_STORM_RANGE || msg == ACTMES_SPIN_STORM_RANGE) {
        return hit();
    }
    return false;
}

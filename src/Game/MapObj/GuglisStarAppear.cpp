// The Power Star of a mod's challenge (Game/MapObj/GuglisStarAppear.hpp, native/CUSTOM_GALAXY.md).
#include "Game/MapObj/GuglisStarAppear.hpp"
#include "Game/Util.hpp"

GuglisStarAppear::GuglisStarAppear(const char* pName) : LiveActor(pName), mDone(false) {
}

void GuglisStarAppear::init(const JMapInfoIter& rIter) {
    MR::initDefaultPos(this, rIter);
    MR::connectToSceneMapObjMovement(this);
    MR::useStageSwitchReadA(this, rIter);
    MR::declarePowerStar(this);  // matched to the scenario by AppearPowerStarObj
    MR::invalidateClipping(this);
    makeActorAppeared();
}

void GuglisStarAppear::control() {
    if (!mDone && MR::isValidSwitchA(this) && MR::isOnSwitchA(this)) {
        mDone = true;
        MR::requestAppearPowerStar(this, mPosition);
    }
}

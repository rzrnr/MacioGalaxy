#pragma once

#include "Game/LiveActor/LiveActor.hpp"

// Makes the scenario's Power Star appear here when stage switch A turns on (native/CUSTOM_GALAXY.md):
// a challenge for a mod's galaxy, e.g. a GroupSwitchWatcher that turns switch A on once every
// GuglisSpinBox has burst. Its placement name must be the scenario's AppearPowerStarObj. No model;
// not part of the original game.
class GuglisStarAppear : public LiveActor {
public:
    GuglisStarAppear(const char* pName);

    virtual void init(const JMapInfoIter& rIter);
    virtual void control();

private:
    bool mDone;
};

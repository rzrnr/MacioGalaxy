#pragma once

#include "Game/LiveActor/LiveActor.hpp"

// Example of a new object with its own logic (native/CUSTOM_GALAXY.md), placed by name like any
// original object: a box (the Punch Box's model) that floats, turns and bobs. Each spin attack
// pays out a coin and makes it swell for a moment; at the last hit it bursts into a ring of coins.
// Obj_arg0: hits until it bursts (default 5); SW_DEAD: a stage switch it turns on when it bursts.
// Not part of the original game.
class GuglisSpinBox : public LiveActor {
public:
    GuglisSpinBox(const char* pName);

    virtual void init(const JMapInfoIter& rIter);
    virtual void control();
    virtual bool receiveMsgPlayerAttack(u32 msg, HitSensor* pSender, HitSensor* pReceiver);
    virtual bool receiveOtherMsg(u32 msg, HitSensor* pSender, HitSensor* pReceiver);

    void exeWait();
    void exeHit();
    void exeBurst();

private:
    bool hit();

    TVec3f mBasePos;
    TVec3f mBaseScale;
    s32 mHitsLeft;
    s32 mTime;
};
